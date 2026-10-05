import os
import re
import glob

def split_all():
    svgs = glob.glob("out/*.svg")
    # Only split the main sheets and fit test
    targets = [f for f in svgs if re.match(r'^out[\\/]0[0-4]_(sheet_[A-D]|fit_test)\.svg$', f)]
    
    for path in targets:
        print(f"Splitting {path}...")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            
        header_match = re.search(r'^(.*?)<g ', content, re.DOTALL)
        if not header_match:
            continue
        header = header_match.group(1)
        
        # Match <g ...> ... </g>
        groups = re.findall(r'(<g id="([^"]+)".*?</g>)', content, re.DOTALL)
        
        base_name = os.path.splitext(path)[0]
        for full_g, layer_id in groups:
            # We skip the frame since it's just the 300x300 bounding box reference
            if layer_id == "frame":
                continue
                
            out_path = f"{base_name}_{layer_id}.svg"
            with open(out_path, "w", encoding="utf-8") as out:
                out.write(header)
                out.write(full_g + "\n")
                out.write("</svg>\n")
            print(f"  Created: {out_path}")

if __name__ == "__main__":
    split_all()
    print("Done! You can now load these separated SVGs into LaserGRBL.")
