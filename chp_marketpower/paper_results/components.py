"""PTDF price and transmission-settlement accounting under the archived signs."""
import numpy as np


def price_components(eq_dual,ineq_dual,ptdf,hours):
    eq,rows,h=np.asarray(eq_dual),np.asarray(ineq_dual),np.asarray(ptdf)
    if h.ndim!=2 or eq.shape[-1]<hours or rows.shape[-1]<2*len(h)*hours:
        raise ValueError('Dual dimensions do not contain the declared network blocks')
    energy=eq[...,-hours:]
    mu=-rows[...,-2*len(h)*hours:].reshape(rows.shape[:-1]+(len(h),hours,2))
    if not np.isfinite(energy).all() or not np.isfinite(mu).all() or np.min(mu)<-1e-7:
        raise ValueError('Invalid complete dual or wrong inequality sign convention')
    congestion=-np.einsum('ln,...lt->...nt',h,mu[...,0]-mu[...,1])
    return energy,congestion,mu


def transmission_adjustment(mu,capacity,physical_flow):
    mu,f,cap=np.asarray(mu),np.asarray(physical_flow),np.asarray(capacity)[:,None]
    if mu.shape!=f.shape+(2,) or np.max(abs(f)-cap)>1e-7 or np.min(mu)<-1e-7:
        raise ValueError('Transmission settlement requires feasible physical flows and positive duals')
    return float(np.sum(mu[...,0]*(cap-f)+mu[...,1]*(cap+f)))


def interpolate(boundaries,values,delta,side='right'):
    b=np.asarray(boundaries)
    if side not in ('left','right') or not np.all(np.diff(b)>0) or not b[0]<=delta<=b[-1]:
        raise ValueError('Expected a strictly ordered domain and a declared interpolation side')
    k=max(0,min(int(np.searchsorted(b,delta,side=side))-1,len(b)-2))
    theta=(delta-b[k])/(b[k+1]-b[k])
    return (1-theta)*values[k]+theta*values[k+1]
