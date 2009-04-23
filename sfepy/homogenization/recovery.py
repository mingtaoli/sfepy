from sfepy.base.base import *
from sfepy.base.ioutils import get_print_info
from sfepy.homogenization.utils import coor_to_sym

shared = Struct()

#
# TODO : interpolate fvars to macro times. ?mid-points?
#

def convolve_field_scalar( fvars, pvars, iel, ts ):
    """
    \int_0^t f(t-s) p(s) ds, t is given by step

    f: fvars ... scalar field variables, defined in a micro domain
    p: pvars ... scalar point variables, a scalar in a point of macro-domain,
    FMField style

    pvars have shape [step][fmf dims]
    fvars have shape [n_step][var dims]
    """

    step0 = max( 0, ts.step - fvars.steps[-1] )
##     print step0, ts.step

    val = nm.zeros_like( fvars[0] )
    for ik in xrange( step0, ts.step + 1 ):
##         print ' ', ik, ts.step-ik
        vf = fvars[ts.step-ik]
        vp = pvars[ik][iel,0,0,0]
        val += vf * vp * ts.dt

    return val

def convolve_field_sym_tensor( fvars, pvars, var_name, dim, iel, ts ):
    """
    \int_0^t f^{ij}(t-s) p_{ij}(s) ds, t is given by step

    f: fvars ... field variables, defined in a micro domain
    p: pvars ... sym. tensor point variables, a scalar in a point of
    macro-domain, FMField style

    pvars have shape [step][fmf dims]
    fvars have shape [dim, dim][var_name][n_step][var dims]
    """

    step0 = max( 0, ts.step - fvars[0,0][var_name].steps[-1] )
##     print step0, ts.step

    val = nm.zeros_like( fvars[0,0][var_name][0] )
    for ik in xrange( step0, ts.step + 1 ):
##         print ' ', ik, ts.step-ik
        for ir in range( dim ):
            for ic in range( dim ):
                ii = coor_to_sym( ir, ic, dim )
                vf = fvars[ir,ic][var_name][ts.step-ik]
                vp = pvars[ik][iel,0,ii,0]
                val += vf * vp * ts.dt
    return val

def add_strain_rs( corrs_rs, strain, vu, dim, iel, out = None ):
    if out is None:
        out = nm.zeros_like( corrs_rs[0,0][vu][0] )

    for ir in range( dim ):
        for ic in range( dim ):
            ii = coor_to_sym( ir, ic, dim )
            out += corrs_rs[ir,ic][vu].data * strain[iel,0,ii,0]
    return out

def compute_u_corr_steady( corrs_rs, strain, corrs_pressure, pressure,
                           vu, dim, iel ):
    """
    $\sum_{ij}\left [ \bar\omegabf^{ij}e_{ij}(\ub(t)) \right ]
    + \omegabf^{*,P} p(t)$

    iel = element number
    """
    u_corr = corrs_pressure[vu].data * pressure[iel,0,0,0]
    add_strain_rs( corrs_rs, strain, vu, dim, iel, out = u_corr )
    return u_corr

def compute_u_corr_time( corrs_rs, dstrains, corrs_pressure, pressures,
                         vu, dim, iel, ts ):
    """
    $\sum_{ij}\left [ \int_0^t \tilde\omegabf^{ij}(t-s)
    \dt{}{s}e_{ij}(\ub(s))\,ds\right ]
    + \int_0^t \tilde\omegabf^P(t-s)\,p(s)\,ds\right ]$
    """
    u_corr = convolve_field_scalar( corrs_pressure[vu], pressures,
                                    iel, ts )
    u_corr += convolve_field_sym_tensor( corrs_rs, dstrains, vu,
                                         dim, iel, ts )
    return u_corr

def compute_p_corr_steady( corrs_pressure, pressure, vp, iel ):
    """
    $\tilde\pi^P(0)p(t)$
    """
    p_corr = corrs_pressure[vp].data * pressure[iel,0,0,0]
    return p_corr

def compute_p_corr_time( corrs_rs, dstrains, corrs_pressure, pressures,
                         vdp, dim, iel, ts ):
    """
    $\sum_{ij} \int_0^t \dt{}{t}\tilde\pi^{ij}(t-s) \dt{}{s}e_{ij}(\ub(s))\,ds
    + \int_0^t \dt{}{t}\tilde\pi^P(t-s)\,p(s)\,ds$
    """
    p_corr = convolve_field_scalar( corrs_pressure[vdp], pressures,
                                    iel, ts )
    p_corr += convolve_field_sym_tensor( corrs_rs, dstrains, vdp,
                                         dim, iel, ts )
    return p_corr

def compute_u_from_macro( strain, coor, iel ):
    """
    Macro-induced displacements.
    
    e_{ij}^x(\ub(t))\,y_j
    """
    n_nod, dim = coor.shape
    um = nm.empty( (n_nod * dim,), dtype = nm.float64 )
    for ir in range( dim ):
        for ic in range( dim ):
            ii = coor_to_sym( ir, ic, dim )
            um[ir::dim] = strain[iel,0,ii,0] * coor[:,ic]
    return um

def recover_bones( problem, micro_problem, region,
                   ts, strain, dstrains, pressure, pressures,
                   corrs_rs, corrs_pressure,
                   corrs_time_rs, corrs_time_pressure,
                   var_names, naming_scheme = 'step_iel' ):
    """
    note that \tilde{\pi}^P(0) is in corrs_pressure
    -> from time correctors only 'u', 'dp' are needed.
    """
    
##     print strain
##     print strain.shape
##     print dstrains
##     print pressure
##     print pressure.shape
##     print pressures

    dim = problem.domain.mesh.dim

    vu, vp = var_names
    vdp = 'd' + vp

    micro_u = micro_problem.variables[vu]
    micro_coor = micro_u.field.get_coor()

    micro_n_nod = micro_problem.domain.mesh.n_nod
    micro_p = micro_problem.variables[vp]

    to_output = micro_problem.variables.state_to_output

    join = os.path.join
    format = get_print_info( problem.domain.mesh.n_el, fill = '0' )[1]

    # single group only!!!
    cells = region.cells[0]
    for ii, iel in enumerate( cells ):
        print 'ii: %d, iel: %d' % (ii, iel)
        u_corr_steady = compute_u_corr_steady( corrs_rs, strain,
                                               corrs_pressure, pressure,
                                               vu, dim, ii )
        u_corr_time = compute_u_corr_time( corrs_time_rs, dstrains,
                                           corrs_time_pressure, pressures,
                                           vu, dim, ii, ts )

        p_corr_steady = compute_p_corr_steady( corrs_pressure, pressure, vp, ii )

        p_corr_time = compute_p_corr_time( corrs_time_rs, dstrains,
                                           corrs_time_pressure, pressures,
                                           vdp, dim, ii, ts )
##     print u_corr_steady
##     print u_corr_time
##     print p_coor_steady
##     print p_corr_time

        u_corr = u_corr_steady + u_corr_time
        p_corr = p_corr_steady + p_corr_time

        u_mic = compute_u_from_macro( strain, micro_coor, ii ) + u_corr
        p_mic = micro_p.extend_data( p_corr[:,nm.newaxis], micro_n_nod,
                                     val = pressure[ii,0,0,0] ).squeeze()

##         print u_mic
##         print p_mic
    
        out = {}
        out.update( to_output( u_mic, var_info = {vu : (True, vu)},
                               extend = True ) )
        out.update( to_output( p_corr, var_info = {vp : (True, vp)},
                               extend = True,
                               fill_value = pressure[ii,0,0,0] ) )

        if naming_scheme == 'step_iel':
            suffix = '.'.join( (ts.suffix % ts.step, format % iel) )
        else:
            suffix = '.'.join( (format % iel, ts.suffix % ts.step) )
        micro_name = micro_problem.get_output_name( suffix = suffix )
        filename = join( problem.output_dir, 'recovered_' + micro_name )

        micro_problem.save_state( filename, out = out )

def recover_paraflow( problem, micro_problem, region,
                      ts, strain, dstrains, pressures1, pressures2,
                      corrs_rs, corrs_time_rs,
                      corrs_alpha1, corrs_time_alpha1,
                      corrs_alpha2, corrs_time_alpha2,
                      var_names, naming_scheme = 'step_iel' ):

    dim = problem.domain.mesh.dim

    vu, vp = var_names
    vdp = 'd' + vp

    micro_u = micro_problem.variables[vu]
    micro_coor = micro_u.field.get_coor()

    micro_n_nod = micro_problem.domain.mesh.n_nod
    micro_p = micro_problem.variables[vp]

    nodes_y1 = micro_problem.domain.regions['Y1'].all_vertices
    nodes_y2 = micro_problem.domain.regions['Y2'].all_vertices

    to_output = micro_problem.variables.state_to_output

    join = os.path.join
    format = get_print_info( problem.domain.shape.n_gr, fill = '0' )[1] \
             + '_' + get_print_info( problem.domain.mesh.n_el, fill = '0' )[1]

    for ig, ii, iel in region.iter_cells():
        print 'ig: %d, ii: %d, iel: %d' % (ig, ii, iel)

        p1, p2 = pressures1[-1][ii,0,0,0], pressures2[-1][ii,0,0,0]

        us = corrs_alpha1[vu].data * p1 + corrs_alpha2[vu].data * p2
        add_strain_rs( corrs_rs, strain, vu, dim, ii, out = us )

        ut = convolve_field_scalar( corrs_time_alpha1[vu], pressures1, ii, ts )
        ut += convolve_field_scalar( corrs_time_alpha2[vu], pressures2, ii, ts )
        ut += convolve_field_sym_tensor( corrs_time_rs, dstrains, vu,
                                         dim, ii, ts )

        u_corr = us + ut
        u_mic = compute_u_from_macro( strain, micro_coor, ii ) + u_corr

        ps = corrs_alpha1[vp].data * p1 + corrs_alpha2[vp].data * p2


        pt = convolve_field_scalar( corrs_time_alpha1[vdp], pressures1,
                                    ii, ts )
        pt += convolve_field_scalar( corrs_time_alpha2[vdp], pressures2,
                                     ii, ts )
        pt += convolve_field_sym_tensor( corrs_time_rs, dstrains, vdp,
                                         dim, ii, ts )

        p_corr = ps + pt

        p_mic = micro_p.extend_data( p_corr[:,nm.newaxis], micro_n_nod )
        p_mic[nodes_y1] = p1
        p_mic[nodes_y2] = p2
        
        out = {}
        out.update( to_output( u_mic, var_info = {vu : (True, vu)},
                               extend = True ) )
        out[vp] = Struct( name = 'output_data',
                          mode = 'vertex', data = p_mic,
                          var_name = vp, dofs = micro_p.dofs )

        if naming_scheme == 'step_iel':
            suffix = '.'.join( (ts.suffix % ts.step, format % (ig, iel)) )
        else:
            suffix = '.'.join( (format % (ig, iel), ts.suffix % ts.step) )
        micro_name = micro_problem.get_output_name( suffix = suffix )
        filename = join( problem.output_dir, 'recovered_' + micro_name )

        micro_problem.save_state( filename, out = out )
