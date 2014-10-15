from __future__ import print_function, division, absolute_import
import numpy as np

from numba import types
from numba import unittest_support as unittest
from numba.compiler import compile_isolated, Flags
from .support import TestCase


looplift_flags = Flags()
looplift_flags.set("enable_pyobject")
looplift_flags.set("enable_looplift")

pyobject_looplift_flags = looplift_flags.copy()
pyobject_looplift_flags.set("enable_pyobject_looplift")


def lift1(x):
    # Outer needs object mode because of np.empty()
    a = np.empty(3)
    for i in range(a.size):
        # Inner is nopython-compliant
        a[i] = x
    return a


def lift2(x):
    # Outer needs object mode because of np.empty()
    a = np.empty((3, 4))
    for i in range(a.shape[0]):
        for j in range(a.shape[1]):
            # Inner is nopython-compliant
            a[i, j] = x
    return a


def lift3(x):
    # Output variable from the loop
    a = np.arange(5, dtype=np.int64)
    c = 0
    for i in range(a.shape[0]):
        c += a[i] * x
    return c


def reject1(x):
    a = np.arange(4)
    for i in range(a.shape[0]):
        # Inner returns a variable from outer "scope" => cannot loop-lift
        return a
    return a


def reject2(x):
    a = np.arange(4)
    for i in range(a.shape[0]):
        if i > 2:
            break
    return a


def reject_npm1(x):
    a = np.empty(3, dtype=np.int32)
    for i in range(a.size):
        # Inner uses np.arange() => cannot loop-lift unless
        # enable_pyobject_looplift is enabled.
        a[i] = np.arange(i + 1)[i]

    return a


class TestLoopLifting(TestCase):
    def check_lift_ok(self, pyfunc, argtypes, args):
        """
        Check that pyfunc can loop-lift even in nopython mode.
        """
        cres = compile_isolated(pyfunc, argtypes,
                                flags=looplift_flags)
        # One lifted loop
        self.assertEqual(len(cres.lifted), 1)
        expected = pyfunc(*args)
        got = cres.entry_point(*args)
        self.assertTrue(np.all(expected == got))
        # Check if we have lifted in nopython mode
        jitloop = cres.lifted[0]
        [loopcres] = jitloop._compileinfos.values()
        self.assertTrue(loopcres.fndesc.native)  # Lifted function is native

    def check_no_lift(self, pyfunc, argtypes, args):
        """
        Check that pyfunc can't loop-lift.
        """
        cres = compile_isolated(pyfunc, argtypes,
                                flags=looplift_flags)
        self.assertFalse(cres.lifted)
        expected = pyfunc(*args)
        got = cres.entry_point(*args)
        self.assertTrue(np.all(expected == got))

    def check_no_lift_nopython(self, pyfunc, argtypes, args):
        """
        Check that pyfunc will fail loop-lifting if pyobject mode
        is disabled inside the loop, succeed otherwise.
        """
        cres = compile_isolated(pyfunc, argtypes,
                                flags=looplift_flags)
        self.assertTrue(cres.lifted)
        with self.assertTypingError():
            cres.entry_point(*args)
        cres = compile_isolated(pyfunc, argtypes,
                                flags=pyobject_looplift_flags)
        self.assertTrue(cres.lifted)
        expected = pyfunc(*args)
        got = cres.entry_point(*args)
        self.assertTrue(np.all(expected == got))

    def test_lift1(self):
        self.check_lift_ok(lift1, (types.intp,), (123,))

    def test_lift2(self):
        self.check_lift_ok(lift2, (types.intp,), (123,))

    def test_lift3(self):
        self.check_lift_ok(lift3, (types.intp,), (123,))

    def test_reject1(self):
        self.check_no_lift(reject1, (types.intp,), (123,))

    def test_reject2(self):
        self.check_no_lift(reject2, (types.intp,), (123,))

    def test_reject_npm1(self):
        self.check_no_lift_nopython(reject_npm1, (types.intp,), (123,))


class TestLoopLiftingInAction(TestCase):
    def test_issue_734(self):
        from numba import jit, void, int32, double

        @jit(void(int32, double[:]), forceobj=True)
        def forloop_with_if(u, a):
            if u == 0:
                for i in range(a.shape[0]):
                    a[i] = a[i] * 2.0
            else:
                for i in range(a.shape[0]):
                    a[i] = a[i] + 1.0

        for u in (0, 1):
            nb_a = np.arange(10, dtype='int32')
            np_a = np.arange(10, dtype='int32')
            forloop_with_if(u, nb_a)
            forloop_with_if.py_func(u, np_a)
            self.assertTrue(np.all(nb_a == np_a))

    def test_issue_812(self):
        from numba import jit

        @jit('f8[:](f8[:])', forceobj=True)
        def test(x):
            res = np.zeros(len(x))
            ind = 0
            for ii in range(len(x)):
                ind += 1
                res[ind] = x[ind]
                if x[ind] >= 10:
                    break

            # Invalid loopjitting will miss the usage of `ind` in the
            # following loop.
            for ii in range(ind + 1, len(x)):
                res[ii] = 0
            return res

        x = np.array([1., 4, 2, -3, 5, 2, 10, 5, 2, 6])
        np.testing.assert_equal(test.py_func(x), test(x))


if __name__ == '__main__':
    unittest.main()