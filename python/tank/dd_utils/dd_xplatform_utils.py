# Confidential and Proprietary Source Code
#
# This Digital Domain Productions, Inc. ("DDPI") source code, including without
# limitation any human-readable computer programming code and associated
# documentation (together "Source Code"), contains valuable confidential,
# proprietary and trade secret information of DDPI and is protected by the laws
# of the United States and other countries. DDPI may, from time to
# time, authorize specific employees to use the Source Code internally at DDPI's
# premises solely for developing, updating, and/or troubleshooting the Source
# Code. Any other use of the Source Code, including without limitation any
# disclosure, copying or reproduction, without the prior written authorization
# of DDPI is strictly prohibited.
#
# Copyright (c) [2013] Digital Domain Productions, Inc. All rights reserved.
#

# STANDARD
import os
import types

# DD
from dd import xplatform

# SETUP LOGGING
from ..log import LogManager
logger = LogManager.get_logger(__name__)


def build_path(*paths):
    """Form a path joining multiple `paths` together using the platform
    dependent path separator. Shell variables contained in `paths` are
    expanded using the :meth:`os.path.expandvars` method.

    >>> build_path('$ABC_PREFIX/python/$PYTHON_VERSION', '$PYTHONPATH')
    '/repository/abc/python/2.7:/repository/xyz/python:/repository/lol/python/2.7'

    Paths that don't map to an actual directory or file on disk will be
    excluded from the resulting path.

    """
    seen = set()
    resolved = []
    unresolved = []
    non_existent = []

    for i, path in enumerate(paths):
        if not isinstance(path, types.StringTypes):
            raise TypeError("item #%s is not a string" % i)
        path = os.path.expandvars(path)
        for p in xplatform.xsplit(path):
            if p in seen:
                continue
            if "$" in p:  # ignore the ones that were partially expanded
                unresolved.append(p)
            elif not os.path.exists(p):
                non_existent.append(p)
            else:
                resolved.append(p)
            seen.add(p)

    if unresolved or non_existent:
        if unresolved:
            logger.debug("expandPaths ignored paths with undefined variables:\n- %s", "\n- ".join(unresolved))
        if non_existent:
            logger.debug("expandPaths ignored paths that don't exist:\n- %s", "\n- ".join(non_existent))
    return xplatform.xjoin(*resolved)


def combine_paths(*paths):
    """Combines all list arguments by applying a string dot product
    operation from left to right.

    >>> paths = combine_paths(['shot', 'seq'], ['devl', 'shared'], ['one', 'two'])
    >>> for path in paths:
    ...   print path
    shot/devl/one
    shot/devl/two
    shot/shared/one
    shot/shared/two
    seq/devl/one
    seq/devl/two
    seq/shared/one
    seq/shared/two

    The concatenation behaviour is the same as :func:`os.path.join`.
    """

    return xplatform.combinePaths(*paths)
