"""Check manuscript assets, references, source-table transcription and build output."""
import csv
import hashlib
import json
from pathlib import Path
import re

import fitz

ROOT = Path(__file__).resolve().parent
PAPER = ROOT.parent / 'paper_results'


def main():
    source = (ROOT / 'main.tex').read_text(encoding='utf-8')
    bibliography = (ROOT / 'references.bib').read_text(encoding='utf-8')
    keys = re.findall(r'@\w+\s*\{\s*([^,]+)', bibliography)
    citations = {key.strip() for group in re.findall(r'\\cite\{([^}]+)\}', source) for key in group.split(',')}
    assert len(keys) == len(set(keys)) and set(keys) == citations
    labels = re.findall(r'\\label\{([^}]+)\}', source)
    refs = re.findall(r'\\(?:eqref|ref)\{([^}]+)\}', source)
    assert len(labels) == len(set(labels)) and set(refs) <= set(labels)
    introduction = source.split(r'\section{Introduction}')[1].split(r'\section{Market Model')[0]
    opening = introduction.split(r'\subsection{Related Work}')[0].strip()
    assert len([p for p in opening.split('\n\n') if p.strip()]) == 3
    contributions = introduction.split(r'\subsection{Our Contributions}')[1]
    assert len(re.findall(r'\\item\b', contributions)) == 3
    assert {'eq:flow', 'eq:aggregation', 'eq:lp-direction', 'eq:dual-feasibility',
            'eq:uc-common', 'eq:uc-probe', 'eq:candidate-value', 'eq:supremum'} <= set(labels)
    assert r'\delta^{\UC}' in source and r'\delta^{\Pi}' in source
    assert r'\delta^*' not in source
    assert len(re.findall(r'\\begin\{figure\*?\}', source)) == 4
    assert len(re.findall(r'\\begin\{table\*?\}', source)) == 2
    figures = [(ROOT / name).resolve() for name in re.findall(r'\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}', source)]
    assert all(path.is_file() for path in figures)
    abstract = source.split(r'\begin{abstract}')[1].split(r'\end{abstract}')[0]
    assert 150 <= len(abstract.split()) <= 200
    assert not re.search(r'\b(?:TODO|TBD|PLACEHOLDER)\b', source)
    tables = re.findall(r'\\begin\{tabular\}.*?\n(.*?)\\end\{tabular\}', source, re.S)
    workload_path = PAPER / 'revision_20261020/source_data/table_I_four_workloads.csv'
    workloads = {(row['instance'], int(row['queries'])): row for row in csv.DictReader(workload_path.open(encoding='utf-8-sig'))}
    for line in tables[0].splitlines():
        if not re.match(r'(?:30|118)-G\d+\s*&', line):
            continue
        fields = [field.strip() for field in line.split('\\\\')[0].split('&')]
        expected = workloads[(fields[0], int(fields[2]))]
        assert int(fields[1]) == int(expected['price_intervals'])
        for value, key in zip(fields[3:], ('direct_seconds', 'parametric_total_seconds', 'direct_over_parametric')):
            assert abs(float(value) - float(expected[key])) <= .0051, (fields[0], key)
    # Compare the manuscript's rounded settlement table to the independently audited ledger.
    settlements = {row['unit']: row for row in csv.DictReader((PAPER / 'source_data/table_II_settlement_changes.csv').open(encoding='utf-8-sig'))}
    for line in tables[1].splitlines():
        if not re.match(r'G[1-6]&', line):
            continue
        fields = line.split('\\\\')[0].replace('$', '').split('&')
        expected = settlements[fields[0]]
        for value, key in zip(fields[1:], ('delta_R', 'delta_U', 'delta_C', 'delta_Pi')):
            assert abs(float(value) - float(expected[key])) <= .0051, (fields[0], key)
    summary = json.loads((PAPER / 'revision_20261020/verification.json').read_text(encoding='utf-8'))
    independent = json.loads((PAPER / 'revision_20261020/independent_verification.json').read_text(encoding='utf-8'))
    assert summary['status'] == independent['status'] == 'passed'
    assert independent['measured_prefixes'] == 2700 and independent['new_optimization_solves'] == 0
    build = json.loads((ROOT / 'compile_attempt.json').read_text(encoding='utf-8-sig'))
    assert build['exitCode'] == 0 and build['pdfExists']
    log = (ROOT / 'build/main.log').read_text(encoding='utf-8', errors='replace')
    assert not re.search(r'Overfull|undefined|LaTeX Error', log)
    pdf = ROOT / 'CHP_market_power_draft.pdf'
    with fitz.open(pdf) as document:
        assert len(document) <= 13
        text = '\n'.join(page.get_text() for page in document)
        assert 'REFERENCES' in text and f'[{len(keys)}]' in text
        pages = len(document)
    sources = [ROOT / 'main.tex', ROOT / 'references.bib', pdf, *figures]
    result = dict(status='passed', pages=pages, manuscript_page_budget=13,
                  introductory_paragraphs=3, contribution_items=3,
                  critical_and_profit_offers_distinguished=True,
                  abstract_words=len(abstract.split()), citations=len(keys),
                  figures=4, tables=2, unresolved_references=0, overfull_boxes=0,
                  settlement_transcription='passed', timing_transcription='passed', new_optimization_solves=0,
                  assets_sha256={str(p.relative_to(ROOT.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (ROOT / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print({key: value for key, value in result.items() if key != 'assets_sha256'})


if __name__ == '__main__':
    main()
