"""Fill mechanically known fields once, shared by Codex and Pi submissions.

Never choose a legal outcome, invent a quote, replace an explicit value, or
turn unknown evidence into a supported fact. Ambiguity remains for review.
"""
import copy
from decimal import Decimal, InvalidOperation
from . import disclosure_contract as contract


def model_schema(schema, stage):
    schema = copy.deepcopy(schema)
    if stage != 'assessment':
        return schema
    schema['required'] = [k for k in schema.get('required', []) if k not in ('assessment_as_of', 'source_ids')]
    # A answers whether/when disclosure is required.  B owns the file set and
    # content granularity, so the runtime does not ask the model to serialize
    # the same plan twice.
    schema.get('properties',{}).pop('preliminary_plan',None)
    for name in ('PlanCandidate','PlanItem','PlannedDocument','Requirement'):
        schema.get('$defs',{}).pop(name,None)
    for name, fields in {'FactBasis': ('source_ref', 'observed_at'),
                         'Reasoning': ('locator', 'quote'), 'Calculation': ('result',)}.items():
        definition = schema.get('$defs', {}).get(name, {})
        definition['required'] = [k for k in definition.get('required', []) if k not in fields]
    return schema


def bind(snapshot, incoming, stage):
    value = copy.deepcopy(incoming)
    changes = []
    if stage != 'assessment'  or not isinstance(value, dict):
        return value, changes
    event, catalog = snapshot['event'], snapshot['catalog']
    as_of = event['facts'].get('assessment_as_of') or event['facts'].get('event_date') or event['created_at'][:10]
    sources = {s['id']: s for s in catalog['sources']}

    def fill(row, key, known, location):
        if key not in row and known is not None:
            row[key] = known
            changes.append({'field': location + '.' + key, 'value': known, 'basis': 'bound_input'})

    fill(value, 'assessment_as_of', as_of, 'assessment')
    facts = value.setdefault('facts', [])
    if not isinstance(facts, list):
        return value, changes
    references=[]
    for matter in value.get('matters',[]):
        if isinstance(matter,dict):
            for row in matter.get('reasoning_items',[])+matter.get('calculations',[]):
                if isinstance(row,dict):references.extend(row.get('fact_keys',[]))
    preview=value.get('preliminary_plan') or {}
    if isinstance(preview,dict):
        for row in preview.get('requirements',[]):
            if isinstance(row,dict):references.extend(row.get('fact_keys',[]))
    known={key:{'key':key,'value':item,'source_ref':'facts.'+key,
               'status':'user_statement' if item is not None else 'unknown','observed_at':as_of}
           for key,item in event.get('facts',{}).items()
           if isinstance(item,(str,int,float,bool)) or item is None}
    explicit={row.get('key') for row in facts if isinstance(row,dict)}
    for key in dict.fromkeys(k for k in references if isinstance(k,str)):
        if key in known and key not in explicit:
            facts.append(copy.deepcopy(known[key]));explicit.add(key)
            changes.append({'field':'facts.'+key,'value':copy.deepcopy(known[key]),'basis':'verbatim_bound_input'})
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            continue
        where = f'facts[{index}]'
        fill(fact, 'observed_at', as_of, where)
        if 'source_ref' not in fact:
            options = []
            if fact.get('key') in event['facts'] and fact.get('value') == event['facts'][fact['key']]:
                options.append('facts.' + fact['key'])
            aliases={'issuer_name':'company_name','company_name':'company_name','stock_code':'stock_code',
                     'issuer_code':'stock_code','board':'board','listing_board':'board'}
            scope_key=aliases.get(fact.get('key'))
            if not options and scope_key and fact.get('value') is not None and fact['value']==contract.scope(event).get(scope_key):
                options.append('scope.'+scope_key)
            quote = fact.get('quote')
            if not options and isinstance(quote, str) and quote and quote in event.get('summary', '') and contract.quoted_value_matches(fact.get('value'), quote):
                options.append('summary')
            if len(options) == 1:
                fill(fact, 'source_ref', options[0], where)
            elif not options and fact.get('status') in ('unknown', 'model_inference', 'conflicting'):
                fill(fact, 'source_ref', 'unverified', where)
    fact_map = {f['key']: f for f in facts if isinstance(f, dict) and 'key' in f}
    referenced = []
    for index, matter in enumerate(value.get('matters', [])):
        if not isinstance(matter, dict):
            continue
        for j, path in enumerate(matter.get('reasoning_items', [])):
            if not isinstance(path, dict):
                continue
            source = sources.get(path.get('source_id'), {})
            if source:
                referenced.append(source['id'])
                fill(path, 'locator', source.get('article'), f'matters[{index}].reasoning_items[{j}]')
                if 0<len(source.get('text',''))<=10000:fill(path,'quote',source['text'],f'matters[{index}].reasoning_items[{j}]')
        # A law ID is unambiguous. Free text is not silently interpreted as a law ID.
        referenced += [sid for sid in matter.get('deadline_basis', []) if isinstance(sid, str) and sid in sources]
        for j, calc in enumerate(matter.get('calculations', [])):
            if not isinstance(calc, dict):
                continue
            if calc.get('basis_source_id') in sources:
                referenced.append(calc['basis_source_id'])
            where = f'matters[{index}].calculations[{j}]'
            if calc.get('scope') == 'snapshot' and calc.get('operation') == 'sum':
                fill(calc, 'basis_source_id', 'facts', where)
            try:
                entries = [fact_map[k] for k in calc['fact_keys']]
                if not entries or any(f.get('status') not in ('user_statement', 'material_supported') for f in entries):
                    continue
                numbers = [Decimal(str(f['value'])) for f in entries]
                if not all(n.is_finite() for n in numbers):
                    continue
                if calc['operation'] == 'sum':
                    result = sum(numbers)
                elif calc['operation'] == 'ratio' and len(numbers) == 2 and numbers[1] != 0:
                    result = contract.ratio_value(numbers[0], numbers[1], calc.get('unit',''))
                else:
                    continue
                fill(calc, 'result', str(result), where)
            except (InvalidOperation, KeyError, ValueError, TypeError):
                continue
    preview = value.get('preliminary_plan') or {}
    if isinstance(preview, dict):
        for group in ('documents', 'requirements', 'drafting_gaps'):
            for row in preview.get(group, []):
                if isinstance(row, dict):
                    referenced += [sid for sid in row.get('source_ids', []) if isinstance(sid, str)]
    if referenced:
        fill(value, 'source_ids', list(dict.fromkeys(referenced)), 'assessment')
        if isinstance(value.get('source_ids'),list) and all(isinstance(x,str) for x in value['source_ids']):
            additions=[sid for sid in dict.fromkeys(referenced) if sid not in value['source_ids']]
            if additions:
                value['source_ids'].extend(additions)
                changes.append({'field':'assessment.source_ids','value':additions,'basis':'sources_already_selected_in_reasoning_or_content'})
    return value, changes
