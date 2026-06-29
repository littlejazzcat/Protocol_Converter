import json
path = r'E:\code\auto_tool\GBT27930_other_protocol\protocol_converter\data\anshibo_1k040b.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)
count = 0
for msg in data['messages']:
    for field in msg['fields']:
        if field.get('name') == '组地址' and field.get('data_type') == 'int_be':
            field['data_type'] = 'bits'
            field['bit_start'] = 4
            field['bit_len'] = 4
            del field['length']
            count += 1
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f'Fixed {count} fields')
