# -*- coding: utf-8 -*-
"""Unit checks; --fixture DIR creates a tiny synthetic ODB with Abaqus Python.

Synthetic model only: two C3D8R elements, two steps, three frames per step.
No solver job is submitted and no research ODB is read or changed.
"""
from __future__ import print_function
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import odb_triaxiality_batch as batch


class Checks(unittest.TestCase):
    def test_filename_rules(self):
        for kind in batch.TYPES:
            self.assertEqual(batch.defect_type('D15_t15_lD05_%s_dt08_Riks.odb' % kind), kind)
            self.assertEqual(batch.defect_type('D20_t2_lD200_%s_dt01_Riks.ODB' % kind.lower()), kind)
        for name in ('D15_SFF.odb', 'D15_SF_DF.odb', 'SF_SF.odb', 'no_rule.odb'):
            with self.assertRaises(ValueError):
                batch.defect_type(name)

    def test_ratios(self):
        self.assertAlmostEqual(batch.ratio(-10.0, 30.0, 0)[0], 1.0 / 3)
        self.assertAlmostEqual(batch.ratio(10.0, 30.0, 0)[0], -1.0 / 3)
        self.assertEqual(batch.ratio(0, 0, 0), (None, 'ZERO_OR_SMALL_MISES'))
        self.assertIsNone(batch.ratio(-1, 1e-12, 1e-9)[0])
        self.assertEqual(batch.ratio(1, float('nan'), 0)[1], 'NONFINITE_STRESS')
        self.assertEqual(batch.ratio(1, -3, 0)[1], 'NEGATIVE_MISES')

    def test_no_interpolation_or_zero_substitution(self):
        rows = batch.combine_curves([(0., 0.), (.1, -10.)], [(0., 0.), (.1, 30.)], 0)
        self.assertIsNone(rows[0][4])
        self.assertAlmostEqual(rows[1][4], 1. / 3)
        with self.assertRaises(ValueError):
            batch.combine_curves([(0., -10.)], [(.1, 30.)], 0)
        with self.assertRaises(ValueError):
            batch.combine_curves([(0., -10.)], [], 0)

    def test_missing_config_is_rejected(self):
        for value in (None, 0, -1, True, 1.5, '25'):
            with self.assertRaises(ValueError):
                batch.point_rules({'position': 'NODAL', 'node_rules': {
                    'SF': {'IP': {'instance': 'P-1', 'node': value}}}}, 'SF')

    def test_xlsx_numeric_blanks_and_safe_strings(self):
        folder = tempfile.mkdtemp(prefix='triax_unit_')
        path = os.path.join(folder, 'check.xlsx')
        try:
            batch.write_xlsx(path, [('TP_IP', [['X', 'Y', 'Comment'], [0., None, '=1+1'], [.1, 1. / 3, u'\uc548\ucabd & <IP>']])])
            with zipfile.ZipFile(path) as z:
                self.assertIsNone(z.testzip())
                for name in z.namelist():
                    if name.endswith(('.xml', '.rels')):
                        ET.fromstring(z.read(name))
                root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
                ns = {'s': batch.NS}
                self.assertFalse(root.findall('.//s:f', ns))
                cells = dict((cell.attrib['r'], cell) for cell in root.findall('.//s:c', ns))
                self.assertIsNone(cells['B2'].find('s:v', ns))
                self.assertAlmostEqual(float(cells['B3'].find('s:v', ns).text), 1. / 3)
                self.assertEqual(cells['C2'].attrib['t'], 'inlineStr')
            with self.assertRaises(ValueError):
                batch.write_xlsx(path, [('TP_IP', [['X']])])
        finally:
            os.remove(path)
            os.rmdir(folder)


def create_fixture(folder):
    from odbAccess import Odb
    from abaqusConstants import THREE_D, DEFORMABLE_BODY, TIME, TENSOR_3D_FULL, MISES, PRESS, INTEGRATION_POINT
    if not os.path.isdir(folder):
        os.makedirs(folder)
    odb_folder = os.path.join(folder, 'odb')
    if not os.path.isdir(odb_folder):
        os.makedirs(odb_folder)
    path = os.path.join(odb_folder, 'SYNTHETIC_SW_case.odb')
    if os.path.exists(path):
        raise ValueError('Choose a fresh fixture directory; refusing to overwrite')
    odb = Odb(name='triax_fixture', analysisTitle='Synthetic triaxiality check',
              description='Verification fixture, not research output', path=path)
    part = odb.Part(name='BLOCK', embeddedSpace=THREE_D, type=DEFORMABLE_BODY)
    part.addNodes(nodeData=((1,0.,0.,0.), (2,1.,0.,0.), (3,1.,1.,0.), (4,0.,1.,0.),
                           (5,0.,0.,1.), (6,1.,0.,1.), (7,1.,1.,1.), (8,0.,1.,1.),
                           (9,2.,0.,0.), (10,2.,1.,0.), (11,2.,0.,1.), (12,2.,1.,1.)))
    part.addElements(elementData=((1,1,2,3,4,5,6,7,8), (2,2,9,10,3,6,11,12,7)), type='C3D8R')
    instance = odb.rootAssembly.Instance(name='BLOCK-1', object=part)
    for step_index in range(2):
        step = odb.Step(name='Step-%d' % (step_index+1), description='Synthetic', domain=TIME, timePeriod=1.)
        for index in range(3):
            frame = step.Frame(incrementNumber=index, frameValue=index * .5, description='Synthetic frame')
            a = float(index)
            field = frame.FieldOutput(name='S', description='Stress', type=TENSOR_3D_FULL,
                                      validInvariants=(MISES, PRESS))
            field.addData(position=INTEGRATION_POINT, instance=instance, labels=(1,2),
                          data=((3*a,0.,0.,0.,0.,0.), (3*a,6*a,3*a,0.,0.,0.)))
            step.setDefaultField(field)
    odb.save()
    odb.close()
    config = {'odb_folder': odb_folder, 'output_folder': os.path.join(folder, 'results'),
              'position': 'NODAL', 'steps': None, 'recursive': False,
              'mises_zero_tolerance': 0, 'max_frames_per_step': None,
              'node_rules': {'SW': {'IP': {'instance': 'BLOCK-1', 'node': 1},
                                    'OP': {'instance': 'BLOCK-1', 'node': 9}}}}
    with io.open(os.path.join(folder, 'config.json'), 'w', encoding='utf-8') as stream:
        stream.write(batch.text_type(json.dumps(config, indent=2)))
    with open(path, 'rb') as stream:
        digest = hashlib.sha256(stream.read()).hexdigest()
    with io.open(os.path.join(folder, 'source_sha256.txt'), 'w', encoding='ascii') as stream:
        stream.write(batch.text_type(digest))
    print('Fixture created: ' + path)


def verify_fixture(folder):
    path = os.path.join(folder, 'odb', 'SYNTHETIC_SW_case.odb')
    with open(path, 'rb') as stream:
        digest = hashlib.sha256(stream.read()).hexdigest()
    with io.open(os.path.join(folder, 'source_sha256.txt'), encoding='ascii') as stream:
        assert digest == stream.read(), 'Source ODB changed'
    reports = []
    for root, dirs, files in os.walk(os.path.join(folder, 'results')):
        if 'batch_report.json' in files:
            reports.append(os.path.join(root, 'batch_report.json'))
    assert reports, 'No batch report'
    for report_path in [max(reports, key=os.path.getmtime)]:
        with io.open(report_path, encoding='utf-8') as stream:
            report = json.load(stream)
        assert len(report) == 1 and report[0]['status'] == 'OK', report
        assert report[0]['samples'] == 6, report
        assert report[0]['invalid_ratios'] == 4, report
        with zipfile.ZipFile(report[0]['workbook']) as archive:
            for sheet_number, expected in ((2, 1. / 3), (3, 4. / 3)):
                root = ET.fromstring(archive.read('xl/worksheets/sheet%d.xml' % sheet_number))
                ns = {'s': batch.NS}
                values = []
                blanks = 0
                for cell in root.findall('.//s:c', ns):
                    if cell.attrib['r'].startswith('F') and cell.attrib['r'] != 'F1':
                        value = cell.find('s:v', ns)
                        if value is None:
                            blanks += 1
                        else:
                            values.append(float(value.text))
                assert blanks == 2 and len(values) == 4, (blanks, values)
                assert all(abs(value - expected) < 1e-6 for value in values), values
    print('PASS: two steps, IP=1/3, OP=4/3, zero-Mises blanks, source ODB SHA256 unchanged')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fixture':
        create_fixture(os.path.abspath(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == '--verify':
        verify_fixture(os.path.abspath(sys.argv[2]))
    else:
        unittest.main()
