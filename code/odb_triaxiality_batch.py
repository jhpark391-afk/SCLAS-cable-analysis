# -*- coding: utf-8 -*-
"""Batch CAE XY-field extraction; Python 2.7/3 compatible, no Excel packages.

Use the 2019/2026 launchers with Abaqus/CAE, or --plan with ordinary Python.
Source ODBs are opened read-only and are never upgraded or saved by this tool.
"""
from __future__ import print_function

import argparse
import datetime
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import zipfile
from xml.sax.saxutils import escape

try:
    text_type = unicode
    integer_types = (int, long)
except NameError:
    text_type = str
    integer_types = (int,)

HERE = os.path.dirname(os.path.abspath(__file__))
TYPES = ('SF', 'DF', 'FF', 'SW')
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
PROGRESS_PATH = None


def log(message):
    line = time.strftime('%H:%M:%S') + ' ' + message
    print(line)
    sys.stdout.flush()
    if PROGRESS_PATH:
        with io.open(PROGRESS_PATH, 'a', encoding='utf-8') as stream:
            stream.write(text_type(line) + u'\n')


def defect_type(path):
    tokens = os.path.splitext(os.path.basename(path))[0].upper().split('_')
    hits = [token for token in tokens if token in TYPES]
    if len(hits) != 1:
        raise ValueError('Expected exactly one SF/DF/FF/SW token: ' + path)
    return hits[0]


def read_config(path):
    with io.open(path, 'r', encoding='utf-8-sig') as stream:
        config = json.load(stream)
    for key in ('odb_folder', 'output_folder'):
        config[key] = os.path.abspath(os.path.join(os.path.dirname(path), config[key]))
    if not os.path.isdir(config['odb_folder']):
        raise ValueError('ODB folder does not exist: ' + config['odb_folder'])
    if config.get('position') != 'NODAL':
        raise ValueError('This node-only exporter supports NODAL (Unique Nodal). Confirm GUI Position before research use.')
    tolerance = config.get('mises_zero_tolerance', 0.0)
    if not isinstance(tolerance, (int, float)) or not finite(tolerance) or tolerance < 0:
        raise ValueError('mises_zero_tolerance must be finite and >= 0')
    steps = config.get('steps')
    if steps is not None and (not isinstance(steps, list) or not steps or
                             any(not isinstance(x, text_type) for x in steps) or
                             len(set(steps)) != len(steps)):
        raise ValueError('steps must be null or a nonempty list of unique names')
    return config


def point_rules(config, kind):
    rule = config.get('node_rules', {}).get(kind, {})
    for point in ('IP', 'OP'):
        item = rule.get(point, {})
        node = item.get('node')
        if isinstance(node, bool) or not isinstance(node, integer_types) or node <= 0:
            raise ValueError('%s %s: set a positive integer node label' % (kind, point))
        if not item.get('instance'):
            raise ValueError('%s %s: set the Instance name' % (kind, point))
    return rule


def find_files(config):
    result = []
    for root, dirs, files in os.walk(config['odb_folder']):
        dirs[:] = sorted(d for d in dirs if os.path.abspath(os.path.join(root, d)) != config['output_folder'])
        for name in sorted(files):
            if name.lower().endswith('.odb'):
                result.append(os.path.join(root, name))
        if not config.get('recursive', False):
            break
    return sorted(result)


def finite(value):
    return not (math.isnan(value) or math.isinf(value))


def ratio(pressure, mises, tolerance):
    if not finite(pressure) or not finite(mises):
        return None, 'NONFINITE_STRESS'
    if mises < 0:
        return None, 'NEGATIVE_MISES'
    if mises <= tolerance:
        return None, 'ZERO_OR_SMALL_MISES'
    result = -pressure / mises
    return (result, 'OK') if finite(result) else (None, 'NONFINITE_RATIO')


def column_name(index):
    name = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def cell_xml(value, ref, header=False):
    if value is None:
        return '<c r="%s"/>' % ref
    style = ' s="1"' if header else ''
    if isinstance(value, (float,) + integer_types) and not isinstance(value, bool):
        if not finite(float(value)):
            raise ValueError('Nonfinite Excel cell at ' + ref)
        return '<c r="%s"%s><v>%s</v></c>' % (ref, style, text_type(value))
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text_type(value))
    if len(value) > 32767:
        value = value[:32760] + ' [...]'
    return '<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>' % (ref, style, escape(value))


def write_xlsx(path, sheets):
    """Small standard-library XLSX writer; strings are never Excel formulas."""
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    handle, temporary = tempfile.mkstemp(prefix='.triax_', suffix='.xlsx', dir=folder)
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            content_types = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
                             '<Default Extension="xml" ContentType="application/xml"/>',
                             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                             '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
            workbook, relationships = [], []
            for number, (name, rows) in enumerate(sheets, 1):
                if not rows or len(rows) > 1048576:
                    raise ValueError('Empty sheet or Excel row limit exceeded: ' + name)
                count = max(len(row) for row in rows)
                if count > 16384:
                    raise ValueError('Excel column limit exceeded')
                name = escape(name, {'"': '&quot;'})
                workbook.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (name, number, number))
                relationships.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (number, number))
                content_types.append('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % number)
                parts = ['<worksheet xmlns="%s"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="%d" width="22" customWidth="1"/></cols><sheetData>' % (NS, count)]
                for row_number, row in enumerate(rows, 1):
                    parts.append('<row r="%d">%s</row>' % (row_number, ''.join(cell_xml(value, column_name(i) + str(row_number), row_number == 1) for i, value in enumerate(row, 1))))
                parts.append('</sheetData><autoFilter ref="A1:%s%d"/></worksheet>' % (column_name(count), len(rows)))
                archive.writestr('xl/worksheets/sheet%d.xml' % number, ''.join(parts).encode('utf-8'))
            archive.writestr('[Content_Types].xml', ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' + ''.join(content_types) + '</Types>').encode('utf-8'))
            archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            archive.writestr('xl/workbook.xml', ('<workbook xmlns="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>%s</sheets></workbook>' % (NS, ''.join(workbook))).encode('utf-8'))
            relationships.append('<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
            archive.writestr('xl/_rels/workbook.xml.rels', ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(relationships) + '</Relationships>').encode('utf-8'))
            archive.writestr('xl/styles.xml', '<styleSheet xmlns="%s"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>' % NS)
        # Destination is unique per run/case; do not overwrite existing results.
        if os.path.exists(path):
            raise ValueError('Refusing to overwrite: ' + path)
        os.rename(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def same_x(left, right):
    return abs(left - right) <= 1e-10 * max(1.0, abs(left), abs(right))


def combine_curves(pressure, mises, tolerance):
    if not pressure or len(pressure) != len(mises):
        raise ValueError('Pressure/Mises sample count mismatch or empty curve')
    rows = []
    for index, (p, m) in enumerate(zip(pressure, mises)):
        if not finite(p[0]) or not finite(m[0]) or not same_x(p[0], m[0]):
            raise ValueError('Pressure/Mises X mismatch at sample %d' % index)
        value, status = ratio(p[1], m[1], tolerance)
        rows.append([index, p[0], p[1] if finite(p[1]) else None,
                     m[1] if finite(m[1]) else None, value, status])
    return rows


def api_text(value):
    # The 2019 C++ API rejects Python unicode for several String arguments.
    if sys.version_info[0] < 3 and isinstance(value, text_type):
        return value.encode('mbcs' if os.name == 'nt' else 'utf-8')
    return value


def read_curve(session, odb, config, point, invariant, constants):
    position = getattr(constants, config['position'])
    variable = ('S', constants.INTEGRATION_POINT, ((constants.INVARIANT, invariant),))
    if point.get('section_points'):
        variable += (dict((api_text(k), api_text(v)) for k, v in point['section_points'].items()),)
    before = set(session.xyDataObjects.keys())
    try:
        curves = session.xyDataListFromField(
            odb=odb, outputPosition=position, variable=(variable,),
            nodeLabels=((api_text(point['instance']), (str(point['node']),)),))
        candidate_names = [curve.name for curve in curves]
        if len(curves) != 1:
            raise ValueError('%s: expected one XY curve, got %d; check Position/section point' % (invariant, len(curves)) + '; candidates: ' + repr(candidate_names))
        return [(float(x), float(y)) for x, y in curves[0].data]
    finally:
        for name in set(session.xyDataObjects.keys()) - before:
            del session.xyDataObjects[name]


def extract_case(session, constants, path, config, kind, destination, keep_xy):
    rule = point_rules(config, kind)
    # Do not reuse or alter a database already opened by the user.
    for existing in session.odbs.values():
        if os.path.normcase(os.path.abspath(existing.path)) == os.path.normcase(os.path.abspath(path)):
            raise ValueError('ODB already open in this session; close it or use noGUI')
    log('Opening read-only: ' + os.path.basename(path))
    odb = session.openOdb(name=api_text(path), path=api_text(path), readOnly=True)
    all_rows = dict(IP=[], OP=[])
    xy_records = []
    viewport = session.viewports[session.currentViewportName]
    previous_object = viewport.displayedObject
    previous_options = dict((name, getattr(viewport.odbDisplay.basicOptions, name)) for name in
                            ('averageElementOutput', 'averageOnlyDisplayed', 'averagingThreshold'))
    try:
        viewport.setValues(displayedObject=odb)
        viewport.odbDisplay.basicOptions.setValues(averageElementOutput=constants.ON,
            averageOnlyDisplayed=constants.OFF, averagingThreshold=100.0)
        for point in ('IP', 'OP'):
            item = rule[point]
            if api_text(item['instance']) not in odb.rootAssembly.instances:
                raise ValueError('Instance not found: ' + item['instance'])
            odb.rootAssembly.instances[api_text(item['instance'])].getNodeFromLabel(item['node'])
        steps = [api_text(name) for name in config['steps']] if config.get('steps') else list(odb.steps.keys())
        for step_name in steps:
            if step_name not in odb.steps:
                raise ValueError('Step not found: ' + step_name)
            log('  Step: ' + step_name)
            maximum = config.get('max_frames_per_step')
            selection = '0:%d' % (maximum - 1) if maximum else '0:-1'
            session.odbData[odb.name].setValues(activeFrames=((step_name, (selection,)),))
            for point in ('IP', 'OP'):
                log('    %s node %s: Pressure / Mises' % (point, rule[point]['node']))
                pressure = read_curve(session, odb, config, rule[point], 'Pressure', constants)
                mises = read_curve(session, odb, config, rule[point], 'Mises', constants)
                rows = combine_curves(pressure, mises, config.get('mises_zero_tolerance', 0.0))
                all_rows[point].extend([[step_name] + row for row in rows])
                if keep_xy:
                    data = tuple((row[1], row[4]) for row in rows if row[4] is not None)
                    if data:
                        xy_records.append((point, step_name, data))
        left, right = all_rows['IP'], all_rows['OP']
        if not left or len(left) != len(right):
            raise ValueError('IP/OP sample count mismatch or no samples')
        combined = [['Step', 'Sample', 'XY_X', 'IP_Pressure', 'IP_Mises', 'TP_IP', 'IP_Status',
                     'OP_Pressure', 'OP_Mises', 'TP_OP', 'OP_Status']]
        for ip, op in zip(left, right):
            if ip[:2] != op[:2] or not same_x(ip[2], op[2]):
                raise ValueError('IP/OP X alignment mismatch')
            combined.append(ip + op[3:])
        metadata = [['Key', 'Value'], ['Source ODB', path], ['Defect', kind],
                    ['Formula', '-Pressure/Mises; dimensionless'], ['Position', config['position']],
                    ['Stress source', 'S / INTEGRATION_POINT'], ['Python', sys.version],
                    ['Abaqus target', config.get('_target', 'unspecified')],
                    ['Run config', json.dumps(config, ensure_ascii=True, sort_keys=True)],
                    ['X meaning', 'Unmodified Abaqus XY X; Riks X is not physical time.'],
                    ['Sample meaning', 'Zero-based XY sample within step; NOT an ODB frame index.'],
                    ['Averaging', 'Unique Nodal, 100% threshold, all elements; no extra manual averaging.'],
                    ['CAE computeOutput', str(getattr(viewport.odbDisplay.basicOptions, 'computeOrder', 'not exposed'))],
                    ['CAE useRegionBoundaries', str(getattr(viewport.odbDisplay.basicOptions, 'useRegionBoundaries', 'not exposed'))],
                    ['GUI comparison', 'Pending comparison with user reference Position/settings.'],
                    ['Invalid ratio', 'Blank Excel value + status. XY omits invalid samples; never substitutes zero.'],
                    ['Stress unit', 'Original model consistent units; no unit conversion.'],
                    ['ODB handling', 'Read-only; no upgrade, save, or ODB modification.']]
        header = ['Step', 'Sample', 'XY_X', 'Pressure', 'Mises', 'Triaxiality', 'Status']
        sheets = [('Combined', combined), ('TP_IP', [header] + left), ('TP_OP', [header] + right), ('Metadata', metadata)]
        write_xlsx(destination, sheets)
        if keep_xy:
            for point, step_name, data in xy_records:
                # Exact TP_IP/TP_OP in one-step GUI runs; qualify multiple steps.
                name = 'TP_' + point + (('__' + step_name) if len(steps) > 1 else '')
                if name in session.xyDataObjects:
                    name += '__' + str(int(time.time() * 1000))
                session.XYData(name=name, data=data, sourceDescription=api_text('-Pressure/Mises; ' + path))
        return len(left), sum(row[-1] != 'OK' for row in left + right)
    finally:
        try:
            viewport.setValues(displayedObject=previous_object)
            viewport.odbDisplay.basicOptions.setValues(**previous_options)
        finally:
            odb.close()


def main(target=None, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.path.join(HERE, 'odb_triaxiality_config.json'))
    parser.add_argument('--plan', action='store_true', help='Inventory/config validation only; never opens ODBs')
    parser.add_argument('--limit', type=int, default=0, help='Process only first N files; 0 = all')
    parser.add_argument('--only', help='Process one exact ODB basename')
    parser.add_argument('--keep-xy', action='store_true', help='Keep TP_IP/TP_OP in current CAE session; requires one ODB')
    if argv is None:
        if '--' in sys.argv:
            argv = sys.argv[sys.argv.index('--') + 1:]
        elif '-cae' in sys.argv or '-noGUI' in sys.argv:
            # CAE 2019 removes -- but leaves internal kernel arguments.
            start = next((i for i, arg in enumerate(sys.argv) if arg.startswith('--')), len(sys.argv))
            argv = sys.argv[start:]
        else:
            argv = sys.argv[1:]
    args = parser.parse_args(argv)
    config = read_config(os.path.abspath(args.config))
    config['_target'] = target
    if args.limit < 0:
        parser.error('--limit must be >= 0')
    maximum = config.get('max_frames_per_step')
    if maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, integer_types) or maximum < 1):
        parser.error('max_frames_per_step must be null or a positive integer')
    paths = find_files(config)
    if args.only:
        paths = [path for path in paths if os.path.basename(path) == args.only]
    if args.limit:
        paths = paths[:args.limit]
    if not paths:
        raise ValueError('No matching ODB files')
    if args.keep_xy and len(paths) != 1:
        parser.error('--keep-xy requires exactly one selected ODB')
    folder = os.path.join(config['output_folder'], datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    os.makedirs(folder)
    global PROGRESS_PATH
    PROGRESS_PATH = os.path.join(folder, 'progress.log')
    plan = []
    for path in paths:
        kind = ''
        try:
            kind = defect_type(path)
            point_rules(config, kind)
            status, detail = 'READY', ''
        except (ValueError, KeyError, TypeError) as error:
            status, detail = 'CONFIG_REQUIRED', text_type(error)
        plan.append([path, kind, status, detail])
    write_xlsx(os.path.join(folder, 'Inventory.xlsx'), [('Files', [['ODB', 'Defect', 'Status', 'Detail']] + plan)])
    if args.plan:
        for row in plan:
            log('%s: %s [%s]' % (os.path.basename(row[0]), row[1], row[2]))
        log('Inventory only (no stress results): ' + folder)
        return 0
    if not any(row[2] == 'READY' for row in plan):
        log('No configured cases. Edit node_rules; inventory: ' + folder)
        return 2
    if target and ((target == '2019' and sys.version_info[0] != 2) or
                   (target == '2026' and sys.version_info[0] != 3)):
        raise RuntimeError('Use the matching Abaqus CAE executable for target ' + target)
    from abaqus import session
    import visualization  # Creates session.odbData and XY extraction support.
    import abaqusConstants as constants
    report = []
    failures = 0
    report_path = os.path.join(folder, 'batch_report.json')
    for number, (path, kind, status, detail) in enumerate(plan, 1):
        record = dict(odb=path, defect=kind, status=status, detail=detail)
        report.append(record)
        if status == 'READY':
            try:
                basename = '%03d_%s.xlsx' % (number, os.path.splitext(os.path.basename(path))[0])
                destination = os.path.join(folder, basename)
                log('[%d/%d] %s' % (number, len(plan), os.path.basename(path)))
                record['status'] = 'RUNNING'
                with io.open(report_path, 'w', encoding='utf-8') as stream:
                    stream.write(text_type(json.dumps(report, ensure_ascii=True, indent=2)))
                samples, invalid = extract_case(session, constants, path, config, kind, destination, args.keep_xy)
                record.update(status='OK', samples=samples, invalid_ratios=invalid, workbook=destination)
                log('  Saved %d samples, %d undefined ratios: %s' % (samples, invalid, destination))
            except Exception as error:
                record.update(status='ERROR', detail=text_type(error))
                log('  ERROR: ' + text_type(error))
        if record['status'] != 'OK':
            failures += 1
        with io.open(report_path, 'w', encoding='utf-8') as stream:
            stream.write(text_type(json.dumps(report, ensure_ascii=True, indent=2)))
    summary = [['ODB', 'Defect', 'Status', 'Samples per point', 'Undefined ratios', 'Workbook', 'Detail']]
    summary.extend([[r['odb'], r['defect'], r['status'], r.get('samples'), r.get('invalid_ratios'), r.get('workbook', ''), r.get('detail', '')] for r in report])
    write_xlsx(os.path.join(folder, 'Batch_summary.xlsx'), [('Summary', summary)])
    log('Complete. %d/%d cases failed/skipped. Output: %s' % (failures, len(paths), folder))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
