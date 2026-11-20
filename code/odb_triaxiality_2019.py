# -*- coding: utf-8 -*-
"""Abaqus 2019: run with the matching CAE executable, see README."""
from __future__ import print_function
import os
import sys

# Abaqus 2019 noGUI executes scripts without defining __file__.
_candidates = [os.environ.get('HELIX_TRIAX_SCRIPT_DIR', '')]
if globals().get('__file__'):
    _candidates.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _arg in sys.argv:
    _path = _arg.split('=', 1)[-1] if 'noGUI=' in _arg else _arg
    if _path.lower().endswith('.py'):
        _candidates.append(os.path.dirname(os.path.abspath(_path)))
_candidates.extend([os.path.join(os.getcwd(), 'code'), os.getcwd()])
for _directory in _candidates:
    if _directory and os.path.isfile(os.path.join(_directory, 'odb_triaxiality_batch.py')):
        sys.path.insert(0, _directory)
        break
else:
    raise RuntimeError('Cannot locate odb_triaxiality_batch.py; use the BAT launcher.')
from odb_triaxiality_batch import main
if __name__ == '__main__':
    result = main(target='2019')
    if result:
        raise RuntimeError('Batch incomplete; status %d. Read Inventory.xlsx / batch_report.json.' % result)
