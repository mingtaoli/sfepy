import numpy as nm

from sfepy.terms.terms_multilinear import ETermBase

class MassTerm(ETermBase):
    r"""
    Mass term with lumping and RMM support [1]_.

    The lumping parameter can be 'row_sum', 'hrz' or 'none' (default). It
    applies for beta > 0:

    - beta = 0 correponds to the consistent mass matrix;
    - beta = 1 corresponds to the lumped mass matrix;
    - 0 < beta < 1 corresponds to the averaged mass matrix.

    `term_mode` can be None (default), 'DPM' (diagonal projection matrix), or
    'RMM' (reciprocal mass matrix).

    .. [1] González, J.A., Kolman, R., Cho, S.S., Felippa, C.A., Park, K.C.,
           2018. Inverse mass matrix via the method of localized lagrange
           multipliers. International Journal for Numerical Methods in
           Engineering 113, 277–295. https://doi.org/10.1002/nme.5613

    :Definition:

    .. math::
        \int_{\cal{D}} \rho \ul{v} \cdot \ul{u} \\
        A_e \\
        A_e^T (M_e^A)^{-1} A_e

    :Arguments:
        - material: :math:`\rho`
        - material: lumping
        - material: :math:`\beta`
        - virtual/parameter_1: :math:`\ul{v}`
        - state/parameter_2: :math:`\ul{u}`
    """
    name = 'de_mass'
    arg_types = ('material_rho', 'material_lumping', 'material_beta',
                 'virtual', 'state')
    arg_shapes = {'material_rho' : '1, 1', 'material_lumping' : '.: str',
                  'material_beta' : '.: 1',
                  'virtual' : ('D', 'state'), 'state' : 'D'}
    modes = ('weak', 'eval')

    def get_function(self, rho, lumping, beta, virtual, state,
                     mode=None, term_mode=None, diff_var=None, **kwargs):

        if ((term_mode is None)
            and ((lumping == 'none') or (beta == 0.0))):
            # Consistent mass matrix.
            fun = self.make_function(
                '00,i,i', rho, virtual, state, diff_var=diff_var,
            )
            return fun

        _fun = self.make_function(
            '00,i,i', rho, virtual, state, diff_var=state.name,
        )
        self.einfos[None] = self.einfos[state.name]

        if (term_mode in ('RMM', 'DPM')) and (lumping == 'none'):
            lumping = 'row_sum'

        if (term_mode == 'DPM'):
            beta = 1.0

        def fun(out, *fargs):
            # Compute M_C.
            if diff_var is None:
                sh = out.shape
                _out = nm.zeros((sh[0], sh[1], sh[2], sh[2]), dtype=out.dtype)

            else:
                _out = out
            status = _fun(_out, *fargs)

            # Consistent element mass matrices M_C.
            mc = _out if beta == 1.0 else _out.copy()
            # Diagonals of lumped element mass matrices M_L.
            if lumping == 'row_sum':
                mld = mc.sum(-1)

            elif lumping == 'hrz':
                n_bf = mc.shape[-1] // self.region.dim
                det = fargs[2][0][0]
                jrho = det * rho[..., 0, 0]

                diag = nm.einsum('...ii->...i', mc)
                intrho = jrho.sum(axis=1) # Element masses to preserve.
                intdiag = diag[:, 0, :n_bf].sum(axis=1)
                alpha = intrho / intdiag
                mld = alpha[:, None, None] * diag

            else:
                raise ValueError('unknown lumping mode! (%s)' % lumping)

            if beta == 1.0:
                # M_A = M_L.
                eye = nm.eye(mld.shape[-1])
                _out[:] = nm.einsum('can,nm->canm', mld, eye)

            else:
                # M_A = (1 - beta) * M_C + beta * M_L.
                _out[:] = (1.0 - beta) * mc
                outd = nm.einsum('...ii->...i', _out) # View to diagonal.
                outd += beta * mld

            if term_mode == 'RMM':
                # out contains M_A, mld contains A_e diagonal.
                ime = nm.linalg.inv(_out)

                # ce = nm.einsum('cik,ckl,clj->cij', ae, ime, ae)
                _out[:] =  mld[..., None] * ime * mld[:, None, :]

            if diff_var is None:
                earg = self.einfos[None].eargs[2]
                step_cache = earg.arg.evaluate_cache.setdefault('dofs', {})
                cache = step_cache.setdefault(0, {})
                dofs = earg.get_dofs(cache, step_cache, state.name + '.dofs')
                dofs = dofs.reshape((sh[0], sh[2])) # Does a copy!

                # Could be faster by exploiting that mld is a vector.
                out[..., 0] = nm.einsum('caij,cj->cai', _out, dofs)

            return status

        return fun
