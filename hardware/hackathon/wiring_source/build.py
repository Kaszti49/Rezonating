import json, sys, os
here = os.path.dirname(os.path.abspath(__file__))
data = open(os.path.join(here, 'out', 'data.json'), encoding='utf-8').read()
tpl = open(os.path.join(here, 'template.html'), encoding='utf-8').read()
assert '/*__DATA__*/null' in tpl
out = tpl.replace('/*__DATA__*/null', data)
open(sys.argv[1], 'w', encoding='utf-8').write(out)
print('written', len(out))
