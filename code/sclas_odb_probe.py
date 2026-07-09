"""Print a compact inventory of an Abaqus ODB for SCLAS postprocessing."""

from __future__ import print_function

import argparse
import sys


def as_name(obj):
    try:
        return obj.name
    except Exception:
        return None


def scalar_component(data, index):
    try:
        return float(data[index])
    except TypeError:
        return float(data)
    except IndexError:
        return None


def print_names(title, names, limit=40):
    names = list(names)
    print("{0} count={1}".format(title, len(names)))
    for name in names[:limit]:
        print("  {0}".format(name))
    if len(names) > limit:
        print("  ... {0} more".format(len(names) - limit))


def summarize_field(frame, output_name, limit=8):
    if output_name not in frame.fieldOutputs.keys():
        print("Field {0}: missing".format(output_name))
        return
    field = frame.fieldOutputs[output_name]
    values = field.values
    print("Field {0}: values={1}".format(output_name, len(values)))
    shown = 0
    max_abs = None
    max_info = None
    for value in values:
        component = scalar_component(value.data, 0)
        if component is None:
            continue
        abs_component = abs(component)
        if max_abs is None or abs_component > max_abs:
            max_abs = abs_component
            max_info = value
        if abs_component > 0.0 and shown < limit:
            instance = as_name(getattr(value, "instance", None))
            print("  nonzero {0}: instance={1}, node={2}, data={3}".format(
                output_name, instance, getattr(value, "nodeLabel", None), value.data))
            shown += 1
    if max_info is not None:
        instance = as_name(getattr(max_info, "instance", None))
        print("  max_abs_component0: instance={0}, node={1}, value={2}".format(
            instance, getattr(max_info, "nodeLabel", None), max_abs))


def value_identity(value):
    instance = getattr(value, "instance", None)
    instance_name = getattr(instance, "name", None) if instance is not None else None
    return instance_name, getattr(value, "nodeLabel", None)


def find_max_rf1_identity(step):
    best_identity = None
    best_abs_rf1 = 0.0
    for frame in reversed(step.frames):
        if "RF" not in frame.fieldOutputs.keys():
            continue
        for value in frame.fieldOutputs["RF"].values:
            rf1 = scalar_component(value.data, 0)
            if rf1 is None:
                continue
            if abs(rf1) > best_abs_rf1:
                best_abs_rf1 = abs(rf1)
                best_identity = value_identity(value)
        if best_identity and best_abs_rf1 > 0.0:
            return best_identity, best_abs_rf1
    return best_identity, best_abs_rf1


def target_value(frame, output_name, identity):
    if output_name not in frame.fieldOutputs.keys():
        return None
    for value in frame.fieldOutputs[output_name].values:
        if value_identity(value) == identity:
            return value.data
    return None


def update_component_ranges(ranges, data):
    if data is None:
        return
    for index in range(3):
        component = scalar_component(data, index)
        if component is None:
            continue
        key = index + 1
        current = ranges.setdefault(key, {"min": component, "max": component, "abs_max": abs(component)})
        current["min"] = min(current["min"], component)
        current["max"] = max(current["max"], component)
        current["abs_max"] = max(current["abs_max"], abs(component))


def summarize_target_components(step):
    identity, max_abs_rf1 = find_max_rf1_identity(step)
    if not identity:
        print("  Auto RP component ranges: no RF1 candidate")
        return
    u_ranges = {}
    rf_ranges = {}
    for frame in step.frames:
        update_component_ranges(u_ranges, target_value(frame, "U", identity))
        update_component_ranges(rf_ranges, target_value(frame, "RF", identity))
    print("  Auto RP candidate: instance={0}, node={1}, max_abs_rf1={2}".format(
        identity[0], identity[1], max_abs_rf1))
    for label, ranges in (("U", u_ranges), ("RF", rf_ranges)):
        for index in sorted(ranges.keys()):
            item = ranges[index]
            print("    {0}{1}: min={2}, max={3}, abs_max={4}, span={5}".format(
                label, index, item["min"], item["max"], item["abs_max"], item["max"] - item["min"]))


def main(argv):
    parser = argparse.ArgumentParser(description="Probe an Abaqus ODB for SCLAS output names.")
    parser.add_argument("odb_path")
    args = parser.parse_args(argv[1:])

    try:
        from odbAccess import openOdb
    except Exception as exc:
        sys.stderr.write("odbAccess unavailable: {0}\n".format(exc))
        return 1

    odb = openOdb(path=args.odb_path, readOnly=True)
    try:
        root = odb.rootAssembly
        print_names("Assembly node sets", root.nodeSets.keys())
        print_names("Assembly instances", root.instances.keys(), limit=20)
        for instance_name in list(root.instances.keys())[:8]:
            instance = root.instances[instance_name]
            if instance.nodeSets.keys():
                print_names("Instance node sets {0}".format(instance_name), instance.nodeSets.keys(), limit=20)
        print_names("Steps", odb.steps.keys())
        for step_name in odb.steps.keys():
            step = odb.steps[step_name]
            print("Step {0}: frames={1}, historyRegions={2}".format(
                step_name, len(step.frames), len(step.historyRegions.keys())))
            for region_name in list(step.historyRegions.keys())[:20]:
                outputs = step.historyRegions[region_name].historyOutputs
                print("  History region: {0}".format(region_name))
                print("    outputs: {0}".format(", ".join(list(outputs.keys())[:40])))
            if step.frames:
                frame = step.frames[-1]
                print("  Last frame field outputs count={0}".format(len(frame.fieldOutputs.keys())))
                for output_name in ("U", "RF", "UR", "RM"):
                    summarize_field(frame, output_name)
                summarize_target_components(step)
    finally:
        odb.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
