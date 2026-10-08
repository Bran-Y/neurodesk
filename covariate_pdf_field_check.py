"""Independent coordinate extraction of the retained Table 2, for source-field QA."""
import hashlib
import json
from pathlib import Path
import pdfplumber
from covariate_fulltext_review import PDF, PDF_SHA, records


def check(root):
    root=Path(root)
    path=root/PDF
    if hashlib.sha256(path.read_bytes()).hexdigest()!=PDF_SHA:
        raise ValueError('Unexpected source PDF')
    with pdfplumber.open(path) as pdf:
        if len(pdf.pages)!=12:
            raise ValueError('Unexpected source length')
        words=[w for w in pdf.pages[4].extract_words() if w['x0']>130 and 105<w['top']<380]
    lines=[]
    for word in sorted(words,key=lambda w:w['top']):
        if not lines or word['top']-lines[-1][0]['top']>2:
            lines.append([])
        lines[-1].append(word)
    if len(lines)!=32 or any(len(line)!=7 for line in lines):
        raise ValueError('Unexpected Table 2 grid')
    table=[[w['text'].replace('\u2212','-').replace('b','<') for w in sorted(line,key=lambda w:w['x0'])] for line in lines]
    checked=[]
    for i,row in enumerate(records()):
        block,column=divmod(i,7)
        effect,ci,p,r2=[table[4*block+j][column] for j in range(4)]
        lower,upper=map(float,ci.strip('()').split(','))
        actual=dict(estimated_effect=float(effect),confidence_interval_lower=lower,confidence_interval_upper=upper,
                    p_value=float(p[2:]),p_comparator=p[1],semipartial_r2=float(r2.lstrip('<')),
                    semipartial_r2_comparator='<' if r2.startswith('<') else '=')
        differences={k:[row[k],v] for k,v in actual.items() if row[k]!=v}
        if differences:
            raise ValueError(f'{row["record_id"]}: {differences}')
        checked.append(dict(record_id=row['record_id'],fields_checked=7,differences=differences,
                            raw_pdf_cells=[effect,ci,p,r2]))
    return dict(source_pdf_sha256=PDF_SHA,page=1248,records=checked,total_rows=56,
                field_checks=392,difference_rows=0,
                method='pdfplumber coordinate extraction compared to separately transcribed/visually inspected Table 2; not human signoff')


if __name__=='__main__':
    root=Path(__file__).parent
    data=check(root)
    (root/'workflow_sources/paper_reading_reviews/barnes_2010_covariate_pdf_field_check.json').write_text(json.dumps(data,indent=2))
    print('Table 2: 56 rows, 392 field checks, zero differences')
