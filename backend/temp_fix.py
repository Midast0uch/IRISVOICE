"with open('requirements.txt', 'r') as f: lines = f.readlines(); new_lines = [l for l in lines if not ('matcha' in l.lower())]; with open('requirements.txt', 'w') as f: f.writelines(new_lines)"  
