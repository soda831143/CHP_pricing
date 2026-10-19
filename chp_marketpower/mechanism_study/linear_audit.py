"""Full LP KKT checks and coherent linear exposure extrema of an optimal dual face."""
import numpy as np
from scipy import sparse
from coptpy import COPT


def primal_lp_audit(persistent):
    m=persistent.solver._model
    variables=m.getVars();constraints=m.getConstrs()
    x=np.asarray(m.getInfo(COPT.Info.Value,variables))
    c=np.asarray(m.getInfo(COPT.Info.Obj,variables))
    rc=np.asarray(m.getInfo(COPT.Info.RedCost,variables))
    all_dual=np.asarray(m.getInfo(COPT.Info.Dual,constraints))
    eq,b,nf,ns,ineq,h=persistent.matrices
    pi,mu=all_dual[:len(b)],all_dual[len(b):]
    il=np.flatnonzero(persistent.lb>-1e20);iu=np.flatnonzero(persistent.ub<1e20)
    zl=np.zeros_like(c);zu=np.zeros_like(c)
    zl[il]=np.maximum(rc[il],0.);zu[iu]=np.minimum(rc[iu],0.)
    dual=float(b@pi+h@mu+persistent.lb[il]@zl[il]+persistent.ub[iu]@zu[iu])
    residual=dict(primal_feasibility=float(max(np.max(abs(eq@x-b)),np.max(ineq@x-h),
        np.max(persistent.lb-x),np.max(x-persistent.ub),0.)),
        stationarity=float(np.max(abs(c-eq.T@pi-ineq.T@mu-zl-zu))),
        dual_sign=float(max(np.max(mu,initial=0.),0.)),duality_gap=abs(float(c@x)-dual),
        row_complementarity=float(np.max(abs(mu*(h-ineq@x)),initial=0.)),
        bound_complementarity=float(max(np.max(abs(zl[il]*(x[il]-persistent.lb[il])),initial=0.),
                                         np.max(abs(zu[iu]*(persistent.ub[iu]-x[iu])),initial=0.))))
    if any(not np.isfinite(v) or v>1e-6 for v in residual.values()):
        raise ValueError(f'LP KKT audit failed: {residual}')
    persistent.solver._solution_x=x
    return residual,dict(primal=x,objective=c,eq_dual=pi,ineq_dual=mu,lower_dual=zl,upper_dual=zu)


def project_price(persistent,pi,mu):
    eq,b,nf,ns,ineq,h=persistent.matrices
    net=persistent.network
    energy=pi[nf+ns:nf+ns+net.T]
    line=mu[-2*net.N_line*net.T:]
    price=energy[None,:]+net.PTDF.T@(line[0::2].reshape(net.N_line,net.T)-line[1::2].reshape(net.N_line,net.T))
    return price


def price_face_extremes(persistent,point,weight,stage,label):
    """Min/max ONE fixed functional over the complete exact optimal dual face.

    Returned complete vectors are coherent legal prices, not a componentwise box.
    Extrema of this functional are not claimed extrema of nonlinear true profit.
    """
    import gurobi_compat as gp
    gp.cp.Model.addConstrs=gp._orig_addConstrs
    eq,b,nf,ns,ineq,h=persistent.matrices
    n=len(point.objective);neq=len(b);nineq=len(h)
    il=np.flatnonzero(persistent.lb>-1e20);iu=np.flatnonzero(persistent.ub<1e20)
    eye=sparse.eye(n,format='csr')
    stationarity=sparse.hstack([eq.T,ineq.T,eye[:,il],eye[:,iu]],format='csr')
    dual_objective=np.r_[b,h,persistent.lb[il],persistent.ub[iu]]
    matrix=sparse.vstack([stationarity,sparse.csr_matrix(dual_objective[None,:])],format='csr')
    rhs=np.r_[point.objective,point.value]
    lower=np.r_[np.full(neq+nineq,-np.inf),np.zeros(len(il)),np.full(len(iu),-np.inf)]
    upper=np.r_[np.full(neq,np.inf),np.zeros(nineq),np.full(len(il),np.inf),np.zeros(len(iu))]
    # At a fixed optimal primal, complementarity characterizes the same dual face.
    inactive=h-ineq@point.primal>1e-7
    lower[neq+np.flatnonzero(inactive)]=0.
    upper[neq+nineq+np.flatnonzero(point.primal[il]-persistent.lb[il]>1e-7)]=0.
    lower[neq+nineq+len(il)+np.flatnonzero(persistent.ub[iu]-point.primal[iu]>1e-7)]=0.
    direction=np.zeros(len(lower));direction[nf+ns:nf+ns+persistent.network.T]=weight
    bus=persistent.network.gen_bus_idx(0)
    flow_start=neq+nineq-2*persistent.network.N_line*persistent.network.T
    for l in range(persistent.network.N_line):
        for t in range(persistent.network.T):
            k=flow_start+2*(l*persistent.network.T+t)
            direction[k]=persistent.network.PTDF[l,bus]*weight[t]
            direction[k+1]=-direction[k]
    model=gp.Model('CoherentOptimalDualExposure')
    y=model.addMVar(shape=len(lower),lb=lower,ub=upper,nameprefix='dual')
    model.addMConstr(stationarity,y,'E',point.objective,nameprefix='stationarity_with_complementarity')
    model.setMObjective(None,direction,0.,xc=y,sense=gp.GRB.MINIMIZE)
    results=[]
    for name,sense in [('min',gp.GRB.MINIMIZE),('max',gp.GRB.MAXIMIZE)]:
        model.setObjSense(sense)
        stage.call('auxiliary',label+'_'+name,model.optimize)
        status=model.getAttr(COPT.Attr.LpStatus)
        if status!=COPT.OPTIMAL:
            results.append(dict(extreme=name,status=f'nonoptimal_{status}',solver_status=int(status)))
            continue
        vector=np.asarray(model.getInfo(COPT.Info.Value,model.getVars()))
        if max(np.max(abs(matrix@vector-rhs)),np.max(lower-vector),np.max(vector-upper))>1e-6:
            raise ValueError('Optimal-dual-face endpoint violates a full constraint')
        pi,mu=vector[:neq],vector[neq:neq+nineq]
        price=project_price(persistent,pi,mu)
        if abs(float(weight@price[bus])-float(direction@vector))>1e-6:
            raise ValueError('Endpoint price functional projection failed')
        results.append(dict(extreme=name,status='optimal',functional_value=float(direction@vector),
            face_formulation='Complementarity at a certified optimal primal',inactive_slack_threshold=1e-7,
            full_dual_residual=float(np.max(abs(matrix@vector-rhs))),price=price,
            eq_dual=pi,ineq_dual=mu,lower_dual=vector[neq+nineq:neq+nineq+len(il)],
            upper_dual=vector[neq+nineq+len(il):]))
    return results
