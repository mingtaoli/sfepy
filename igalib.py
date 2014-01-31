"""
Isogeometric analysis utilities.

Notes
-----
The function :func:`compute_bezier_extraction_1d()` implements the algorithm
described in [1].

[1] Michael J. Borden, Michael A. Scott, John A. Evans, Thomas J. R. Hughes:
    Isogeometric finite element data structures based on Bezier extraction of
    NURBS, Institute for Computational Engineering and Sciences, The University
    of Texas at Austin, Austin, Texas, March 2010.
"""
import numpy as nm

from sfepy.base.base import assert_

def _get_knots_tuple(knots):
    if isinstance(knots, nm.ndarray) and (knots.ndim == 1):
        knots = (knots,)

    elif not isinstance(knots, tuple):
        raise ValueError('knots must be 1D array or a tuple of 1D arrays!')

    return knots

def get_raveled_index(indices, shape):
    """
    Get a global raveled index corresponding to nD indices into an array of the
    given shape.
    """
    return nm.ravel_multi_index(indices, shape)

def get_unraveled_indices(index, shape):
    """
    Get nD indices into an array of the given shape corresponding to a global
    raveled index.
    """
    return nm.unravel_index(index, shape)

def tensor_product(a, b):
    """
    Compute tensor product of two 2D arrays with possibly different shapes. The
    result has the form
    ``c = [[a00 b, a01 b, ..., ],
           [a10 b, a11 b, ..., ]
           ...``.
    """
    c = nm.empty((a.shape[0] * b.shape[0],
                  a.shape[1] * b.shape[1]), dtype=b.dtype)

    n0 = b.shape[0]
    n1 = b.shape[1]
    for ir in xrange(a.shape[0]):
        for ic in xrange(a.shape[1]):
            c[n1 * ir : n1 * (ir + 1),
              n0 * ic : n0 * (ic + 1)] = a[ir, ic] * b

    return c

def compute_bezier_extraction_1d(knots, degree):
    """
    Compute local (element) Bezier extraction operators for a 1D B-spline
    parametric domain.

    Parameters
    ----------
    knots : array
        The knot vector.
    degree : int
        The curve degree.

    Returns
    -------
    cs : list of 2D arrays
        The element extraction operators.
    """
    knots = nm.asarray(knots, dtype=nm.float64)
    n_knots = knots.shape[0]

    a = degree
    b = a + 1

    # The first element extraction operator.
    cs = [nm.eye(degree + 1, degree + 1, dtype=nm.float64)]
    while (b + 1) < n_knots:
        # The current extraction operator.
        cc = cs[-1]

        # Multiplicity of the knot at location b.
        b0 = b
        while ((b + 1) < n_knots) and (knots[b] == knots[b + 1]):
            b += 1
        mult = b - b0 + 1

        if mult >= degree:
            continue

        # The next extraction operator.
        cn = nm.eye(degree + 1, degree + 1, dtype=nm.float64)
        cs.append(cn)

        alphas = nm.zeros(degree - mult, dtype=nm.float64)
        numer = knots[b] - knots[a]
        for ij in xrange(degree, mult, -1):
            alphas[ij - mult - 1] = numer / (knots[a + ij] - knots[a])

        r = degree - mult
        for ij in xrange(0, r):
            save = r - ij - 1
            s = mult + ij

            for ik in xrange(degree, s, -1):
                alpha = alphas[ik - s - 1]
                cc[:, ik] = alpha * cc[:, ik] + (1.0 - alpha) * cc[:, ik - 1]

            if (b + 1) < n_knots:
                # Update overlapping coefficients for the next operator.
                cn[save : ij + save + 2,
                   save] = cc[degree - ij - 1: degree + 1, degree]

        if (b + 1) < n_knots:
            # The next knot vector interval.
            a = b
            b = b + 1

    return cs

def compute_bezier_extraction(knots, degrees):
    """
    Compute local (element) Bezier extraction operators for a nD B-spline
    parametric domain.

    Parameters
    ----------
    knots : sequence of array or array
        The knot vectors.
    degrees : sequence of ints or int
        Polynomial degrees in each parametric dimension.

    Returns
    -------
    cs : list of lists of 2D arrays
        The element extraction operators in each parametric dimension.
    """
    if isinstance(degrees, int): degrees = [degrees]

    knots = _get_knots_tuple(knots)
    dim = len(knots)
    assert_(dim == len(degrees))

    cs = []
    for ii, knots1d in enumerate(knots):
        cs1d = compute_bezier_extraction_1d(knots1d, degrees[ii])
        cs.append(cs1d)

    return cs

def combine_bezier_extraction(cs):
    """
    For a nD B-spline parametric domain, combine the 1D element extraction
    operators in each parametric dimension into a single operator for each nD
    element.

    Parameters
    ----------
    cs : list of lists of 2D arrays
        The element extraction operators in each parametric dimension.

    Returns
    -------
    ccs : list of 2D arrays
        The combined element extraction operators.
    """
    dim = len(cs)

    if dim == 3:
        c0, c1, c2 = cs[0], cs[1], cs[2]

        ncc = (len(c0), len(c1), len(c2))
        ccs = [None] * nm.prod(ncc)
        for i0 in xrange(len(c0)):
            for i1 in xrange(len(c1)):
                for i2 in xrange(len(c2)):
                    cc = tensor_product(c0[i0], tensor_product(c1[i1], c2[i2]))
                    ii = get_raveled_index([i0, i1, i2], ncc)
                    ccs[ii] = cc

    elif dim == 2:
        c0, c1 = cs[0], cs[1]

        ncc = (len(c0), len(c1))
        ccs = [None] * nm.prod(ncc)
        for i0 in xrange(len(c0)):
            for i1 in xrange(len(c1)):
                cc = tensor_product(c0[i0], c1[i1])
                ii = get_raveled_index([i0, i1], ncc)
                ccs[ii] = cc

    else:
        ccs = cs[0]

    return ccs

def create_connectivity_1d(n_el, knots, degree):
    """
    Create connectivity arrays of 1D Bezier elements.

    Parameters
    ----------
    n_el : int
        The number of elements.
    knots : array
        The knot vector.
    degree : int
        The basis degree.

    Returns
    -------
    conn : array
        The connectivity of the global NURBS basis.
    bconn : array
        The connectivity of the Bezier basis.
    """
    # Get multiplicities of NURBS knots.
    n_knots = len(knots)
    mul = [0]
    ii = degree + 1
    while ii < (n_knots - degree - 1):
        i0 = ii
        while (ii < (n_knots - degree - 2)) and (knots[ii] == knots[ii + 1]):
            ii += 1
        mul.append(ii - i0 + 1)
        ii += 1

    mul = nm.array(mul)[:, None]

    aux1 = nm.arange(degree + 1)[None, :]
    conn = aux1 + nm.cumsum(mul, 0)

    # Bezier basis knots have multiplicity equal to degree.
    aux2 = nm.arange(n_el)[:, None]
    bconn = aux1 + degree * aux2

    return conn, bconn

def create_connectivity(n_els, knots, degrees):
    """
    Create connectivity arrays of nD Bezier elements.

    Parameters
    ----------
    n_els : sequence of ints
        The number of elements in each parametric dimension.
    knots : sequence of array or array
        The knot vectors.
    degrees : sequence of ints or int
        The basis degrees in each parametric dimension.

    Returns
    -------
    conn : array
        The connectivity of the global NURBS basis.
    bconn : array
        The connectivity of the Bezier basis.
    """
    if isinstance(degrees, int): degrees = [degrees]
    degrees = nm.asarray(degrees)

    knots = _get_knots_tuple(knots)
    dim = len(n_els)
    assert_(dim == len(degrees) == len(knots))

    conns = []
    bconns = []
    n_gfuns = []
    n_gbfuns = []
    for ii, n_el in enumerate(n_els):
        conn1d, bconn1d = create_connectivity_1d(n_el, knots[ii], degrees[ii])
        conns.append(conn1d)
        bconns.append(bconn1d)

        n_gfuns.append(conn1d.max() + 1)
        n_gbfuns.append(bconn1d.max() + 1)

    n_el = nm.prod(n_els)
    n_efuns = degrees + 1
    n_efun = nm.prod(n_efuns)

    if dim == 3:
        def make_conn_3d(conns, n_gfuns):
            conn = nm.empty((n_el, n_efun), dtype=nm.int32)
            for ie0 in xrange(n_els[0]):
                c0 = conns[0][ie0]
                for ie1 in xrange(n_els[1]):
                    c1 = conns[1][ie1]
                    for ie2 in xrange(n_els[2]):
                        c2 = conns[2][ie2]
                        ie = get_raveled_index([ie0, ie1, ie2], n_els)

                        for il0 in xrange(n_efuns[0]):
                            cl0 = c0[il0]
                            for il1 in xrange(n_efuns[1]):
                                cl1 = c1[il1]
                                for il2 in xrange(n_efuns[2]):
                                    cl2 = c2[il2]

                                    iloc = get_raveled_index([il0, il1, il2],
                                                             n_efuns)
                                    ig = get_raveled_index([cl0, cl1, cl2],
                                                           n_gfuns)
                                    conn[ie, iloc] = ig

            return conn

        conn = make_conn_3d(conns, n_gfuns)
        bconn = make_conn_3d(bconns, n_gbfuns)

    elif dim == 2:
        def make_conn_2d(conns, n_gfuns):
            conn = nm.empty((n_el, n_efun), dtype=nm.int32)
            for ie0 in xrange(n_els[0]):
                c0 = conns[0][ie0]
                for ie1 in xrange(n_els[1]):
                    c1 = conns[1][ie1]
                    ie = get_raveled_index([ie0, ie1], n_els)

                    for il0 in xrange(n_efuns[0]):
                        cl0 = c0[il0]
                        for il1 in xrange(n_efuns[1]):
                            cl1 = c1[il1]

                            iloc = get_raveled_index([il0, il1], n_efuns)
                            ig = get_raveled_index([cl0, cl1], n_gfuns)
                            conn[ie, iloc] = ig

            return conn

        conn = make_conn_2d(conns, n_gfuns)
        bconn = make_conn_2d(bconns, n_gbfuns)

    else:
        conn = conns[0]
        bconn = bconns[0]

    return conn, bconn

def compute_bezier_control(control_points, weights, ccs, conn, bconn):
    """
    Compute the control points and weights of the Bezier mesh.

    Parameters
    ----------
    control_points : array
        The NURBS control points.
    weights : array
        The NURBS weights.
    ccs : list of 2D arrays
        The combined element extraction operators.
    conn : array
        The connectivity of the global NURBS basis.
    bconn : array
        The connectivity of the Bezier basis.

    Returns
    -------
    bezier_control_points : array
        The control points of the Bezier mesh.
    bezier_weights : array
        The weights of the Bezier mesh.
    """
    n_bpoints = bconn.max() + 1
    dim = control_points.shape[1]

    bezier_control_points = nm.zeros((n_bpoints, dim), dtype=nm.float64)
    bezier_weights = nm.zeros(n_bpoints, dtype=nm.float64)

    for ie, ec in enumerate(conn):
        cc = ccs[ie]
        bec = bconn[ie]

        ew = weights[ec]
        ecp = control_points[ec]

        bew = nm.dot(cc.T, ew)

        becp = (1.0 / bew[:, None]) * nm.dot(cc.T, ew[:, None] * ecp)
        bezier_control_points[bec] = becp
        bezier_weights[bec] = bew

    return bezier_control_points, bezier_weights

def eval_bernstein_basis(x, degree):
    """
    Evaluate the Bernstein polynomial basis of the given `degree`, and its
    derivatives, in a point `x` in [0, 1].

    Parameters
    ----------
    x : float
        The point in [0, 1].
    degree : int
        The basis degree.

    Returns
    -------
    funs : array
        The `degree + 1` values of the Bernstein polynomial basis.
    ders : array
        The `degree + 1` values of the Bernstein polynomial basis derivatives.
    """
    n_fun = degree + 1

    funs = nm.zeros(n_fun, dtype=nm.float64)
    ders = nm.zeros(n_fun, dtype=nm.float64)

    funs[0] = 1.0

    if degree == 0: return funs, ders

    for ip in xrange(1, n_fun - 1):
        prev = 0.0
        for ifun in xrange(ip + 1):
            tmp = x * funs[ifun]
            funs[ifun] = (1.0 - x) * funs[ifun] + prev
            prev = tmp

    for ifun in xrange(n_fun):
        ders[ifun] = degree * (funs[ifun - 1] - funs[ifun])

    prev = 0.0
    for ifun in xrange(n_fun):
        tmp = x * funs[ifun]
        funs[ifun] = (1.0 - x) * funs[ifun] + prev
        prev = tmp

    return funs, ders
