"""Wire the scan's limitations through the report and the API.

The stored form of a scan's limitations is a JSON document, so it can be
queried. The report is for a reader, so the same information is rendered
as sentences. Nothing is dropped: a partial scan says what it could not
analyse.
"""

import pathlib

HELPER = '''def _limitation_lines(limitations: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Turn a scan's stored limitations into readable sentences.

    The stored form is a JSON document so that it can be queried. The
    report is for a reader, so the same information is rendered as
    sentences, in a fixed order, and nothing is dropped.
    """
    if not limitations:
        return ()

    lines: list[str] = []
    warnings = limitations.get("disassembly_warnings")
    if isinstance(warnings, list) and warnings:
        shown = "; ".join(str(item) for item in warnings[:5])
        more = "" if len(warnings) <= 5 else f" (and {len(warnings) - 5} more)"
        lines.append(f"{len(warnings)} disassembly warning(s): {shown}{more}")

    edges = limitations.get("unresolved_control_flow_edges")
    if isinstance(edges, int):
        ratio = limitations.get("unresolved_edge_ratio")
        detail = f"{edges} control-flow edge(s) could not be resolved statically"
        if isinstance(ratio, (int, float)):
            detail += f" ({float(ratio):.1%} of the graph)"
        lines.append(detail)

    known = {"disassembly_warnings", "unresolved_control_flow_edges", "unresolved_edge_ratio"}
    for key in sorted(limitations):
        if key in known:
            continue
        lines.append(f"{key}: {limitations[key]}")
    return tuple(lines)


'''

RENDER = (
    "    if data.limitations:\n"
    '        blocks.append(_Line("Coverage limitations", "heading"))\n'
    '        blocks.extend(_Line(f"  {line}", "evidence") for line in data.limitations)\n'
    "        blocks.append(\n"
    "            _Line(\n"
    '                "These are the parts of the contract this scan could not "\n'
    '                "analyse. The findings below are what the engines that did "\n'
    '                "run were able to see.",\n'
    '                "body",\n'
    "            )\n"
    "        )\n"
    '        blocks.append(_Line("Findings", "heading"))'
)

FIELD = (
    '    finding_base_url: str = ""\n'
    '    """The base URL a finding is linked back to on the platform.\n'
    "\n"
    "    When set, every finding carries a link to its machine-readable form.\n"
    '    """\n'
    "\n"
    "    limitations: tuple[str, ...] = ()\n"
    '    """What the analysis could not cover, in plain sentences.\n'
    "\n"
    "    A partial scan is not a clean scan with fewer findings. These\n"
    "    lines say what was left out, so a reader can judge the result\n"
    "    instead of having to trust it.\n"
    '    """\n'
)


def main() -> None:
    report = pathlib.Path("apps/api/app/services/report.py")
    s = report.read_text()

    if "limitations: tuple[str, ...] = ()" not in s:
        s = s.replace(
            '    finding_base_url: str = ""\n'
            '    """The base URL a finding is linked back to on the platform.\n'
            "\n"
            "    When set, every finding carries a link to its machine-readable form.\n"
            '    """\n',
            FIELD,
            1,
        )

    if "def _limitation_lines(" not in s:
        s = s.replace("def _engine_summary(", HELPER + "def _engine_summary(", 1)

    if "limitations: Mapping[str, Any] | None = None," not in s:
        s = s.replace(
            '    finding_base_url: str = "",\n) -> ReportData:',
            '    finding_base_url: str = "",\n'
            "    limitations: Mapping[str, Any] | None = None,\n"
            ") -> ReportData:",
            1,
        )

    if "limitations=_limitation_lines(limitations)," not in s:
        s = s.replace(
            "        engines=built_engines,\n",
            "        engines=built_engines,\n        limitations=_limitation_lines(limitations),\n",
            1,
        )

    if 'blocks.append(_Line("Coverage limitations", "heading"))' not in s:
        s = s.replace(
            '    blocks.append(_Line("Findings", "heading"))',
            RENDER,
            1,
        )

    report.write_text(s)
    print("report.py updated")

    api = pathlib.Path("apps/api/app/api/scans.py")
    s = api.read_text()
    if "limitations=scan.limitations," not in s:
        s = s.replace(
            "    data = build_report_data(\n",
            "    data = build_report_data(\n        limitations=scan.limitations,\n",
            1,
        )
        api.write_text(s)
        print("api/scans.py updated")


if __name__ == "__main__":
    main()
