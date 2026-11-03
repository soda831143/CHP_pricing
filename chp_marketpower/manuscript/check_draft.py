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
    assert len(re.findall(r'\\item\b', contributions)) == 2
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
    timing_rows = 0
    for line in '\n'.join(tables).splitlines():
        if not re.match(r'(?:30|118)-G\d+\s*&', line):
            continue
        fields = [field.strip() for field in line.split('\\\\')[0].split('&')]
        timing_rows += 1
        expected = workloads[(fields[0], int(fields[2]))]
        assert int(fields[1]) == int(expected['price_intervals'])
        for value, key in zip(fields[3:], ('direct_seconds', 'parametric_total_seconds', 'direct_over_parametric')):
            assert abs(float(value) - float(expected[key])) <= .0051, (fields[0], key)
    assert timing_rows == len(workloads) == 4
    # Compare the manuscript's rounded settlement table to the independently audited ledger.
    settlements = {row['unit']: row for row in csv.DictReader((PAPER / 'source_data/table_II_settlement_changes.csv').open(encoding='utf-8-sig'))}
    settlement_rows = 0
    for line in '\n'.join(tables).splitlines():
        if not re.match(r'G[1-6]\s*&', line):
            continue
        fields = [field.strip() for field in line.split('\\\\')[0].replace('$', '').split('&')]
        settlement_rows += 1
        expected = settlements[fields[0]]
        for value, key in zip(fields[1:], ('delta_R', 'delta_U', 'delta_C', 'delta_Pi')):
            assert abs(float(value) - float(expected[key])) <= .0051, (fields[0], key)
    assert settlement_rows == len(settlements) == 6
    summary = json.loads((PAPER / 'revision_20261020/verification.json').read_text(encoding='utf-8'))
    independent = json.loads((PAPER / 'revision_20261020/independent_verification.json').read_text(encoding='utf-8'))
    assert summary['status'] == independent['status'] == 'passed'
    assert independent['measured_prefixes'] == 2700 and independent['new_optimization_solves'] == 0
    response_root = PAPER / 'revision_20261021'
    response_check = json.loads((response_root / 'verification.json').read_text(encoding='utf-8'))
    assert response_check['status'] == 'passed' and response_check['new_optimization_solves'] == 0
    assert response_check['physical_boundaries'] == 16 and response_check['nodal_response_comparisons'] == 1440
    fingerprints = json.loads((response_root / 'input_manifest.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((ROOT.parent / p).read_bytes()).hexdigest() == sha for p, sha in fingerprints.items())
    with (response_root / 'source_data/network_response_contrasts.csv').open(encoding='utf-8') as stream:
        contrast = next(csv.DictReader(stream))
    for key, value in [('DDelta_R', -2127.85), ('DDelta_U', 59.92),
                       ('minus_DDelta_C', 2647.77), ('DDelta_Pi', 579.84)]:
        assert abs(float(contrast[key])-value) < .0051
    assert {'eq:tie-system-cost', 'cor:exposure', 'eq:exposure-monotonicity',
            'eq:jump-replacement-cost', 'eq:network-response', 'eq:network-response-result'} <= set(labels)
    factorial_root = PAPER / 'revision_20261102'
    factorial = json.loads((factorial_root / 'verification.json').read_text(encoding='utf-8'))
    assert factorial['status'] == 'passed' and factorial['new_optimization_solves'] == 17
    assert factorial['factorial_cases'] == 12 and factorial['fixed_offers'] == 2
    fingerprints = json.loads((factorial_root / 'input_manifest.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((ROOT.parent / p).read_bytes()).hexdigest() == sha for p, sha in fingerprints.items())
    assert {'eq:competition-gap', 'eq:competitor-exclusion'} <= set(labels)
    with (factorial_root / 'source_data/factorial_settlements.csv').open(encoding='utf-8') as stream:
        cells = list(csv.DictReader(stream))
    for network, epsilon, expected in [('original', 0., 6377.54), ('original', 5., 7695.41),
                                      ('relaxed', 0., 8600.35), ('relaxed', 5., 8693.98)]:
        row = next(r for r in cells if r['network']==network and float(r['epsilon'])==epsilon and r['quote']=='2')
        assert abs(float(row['delta_Pi'])-expected) < .0051
    evidence = json.loads((PAPER / 'evidence_manifest.json').read_text(encoding='utf-8'))
    assert evidence['file_count'] == len(evidence['files'])
    assert all(hashlib.sha256((ROOT.parent.parent / p).read_bytes()).hexdigest() == sha
               for p, sha in evidence['files'].items())
    build = json.loads((ROOT / 'compile_attempt.json').read_text(encoding='utf-8-sig'))
    assert build['exitCode'] == 0 and build['pdfExists']
    log = (ROOT / 'build/main.log').read_text(encoding='utf-8', errors='replace')
    assert not re.search(r'Overfull|undefined|LaTeX Error', log)
    pdf = ROOT / 'CHP_market_power_draft.pdf'
    with fitz.open(pdf) as document:
        text = '\n'.join(page.get_text() for page in document)
        assert 'REFERENCES' in text and f'[{len(keys)}]' in text
        pages = len(document)
    sources = [ROOT / 'main.tex', ROOT / 'references.bib', pdf, *figures]
    result = dict(status='passed', revision='05', date='2026-11-03', pages=pages, manuscript_page_budget=None,
                  introductory_paragraphs=3, contribution_items=2,
                  critical_and_profit_offers_distinguished=True,
                  abstract_words=len(abstract.split()), citations=len(keys),
                  figures=4, tables=2, unresolved_references=0, overfull_boxes=0,
                  settlement_transcription='passed', timing_transcription='passed', new_optimization_solves=0,
                  archived_factorial_optimization_solves=17,
                  network_response_transcription='passed', physical_switching_boundaries=16,
                  factorial_transcription='passed', factorial_conditions=4, fixed_factorial_offers=2,
                  retained_evidence_files=len(evidence['files']),
                  assets_sha256={str(p.relative_to(ROOT.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (ROOT / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print({key: value for key, value in result.items() if key != 'assets_sha256'})


if __name__ == '__main__':
    main()
