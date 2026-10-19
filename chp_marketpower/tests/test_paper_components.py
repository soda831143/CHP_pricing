import numpy as np
import pytest
from paper_results.components import price_components,transmission_adjustment,interpolate


def test_row_sign_reference_bus_and_nodal_reconstruction():
    h=np.array([[0.,.5,-.5]])
    energy,congestion,mu=price_components(np.array([99.,10.,12.]),np.array([-4.,0.,0.,-2.]),h,2)
    np.testing.assert_allclose(energy,[10.,12.])
    np.testing.assert_allclose(congestion,[[0.,0.],[-2.,1.],[2.,-1.]])
    np.testing.assert_allclose(energy[None,:]+congestion,[[10.,12.],[8.,13.],[12.,11.]])
    with pytest.raises(ValueError):price_components([10.,12.],[4.,0.,0.,-2.],h,2)


def test_settlement_uses_physical_flow_not_a_pricing_flow():
    mu=np.array([[[4.,0.],[0.,2.]]]);cap=np.array([5.])
    assert transmission_adjustment(mu,cap,[[3.,-4.]])==10.
    assert transmission_adjustment(mu,cap,[[5.,-5.]])==0.
    with pytest.raises(ValueError):transmission_adjustment(mu,cap,[[6.,-4.]])


def test_reference_change_preserves_total_price_and_not_component_allocation():
    energy=np.array([10.,12.]);c=np.array([[0.,0.],[-2.,1.],[2.,-1.]])
    rebased_energy=energy+c[1];rebased_c=c-c[1]
    np.testing.assert_allclose(rebased_energy+rebased_c,energy+c)
    assert not np.allclose(rebased_energy,energy)


def test_piecewise_selection_continuity_at_shared_boundaries():
    b=[0.,1.,2.];v=np.array([[2.,3.],[3.,5.],[7.,8.]])
    np.testing.assert_array_equal(interpolate(b,v,1.,'left'),interpolate(b,v,1.,'right'))
    with pytest.raises(ValueError):interpolate([0.,0.],v[:2],0.)
