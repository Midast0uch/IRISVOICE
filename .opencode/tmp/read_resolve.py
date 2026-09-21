src = open(r'backend/agent/tools/ask_user_tool.py', encoding='utf-8').read()
i = src.find('def resolve_answer')
seg = src[i:i+3500]
# print the code after the docstring
k = seg.find('"""', seg.find('"""') + 3)  # end of docstring
print(seg[k:k+1800])
