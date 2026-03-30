import os
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF

base = os.path.abspath(os.path.join(os.path.dirname(__file__)))
svgs = ["architecture.svg", "workflow.svg", "data_model.svg", "analytics_plot.svg"]

for name in svgs:
    src = os.path.join(base, name)
    dst = os.path.join(base, os.path.splitext(name)[0] + ".pdf")
    if not os.path.exists(src):
        print(f"Missing {src}")
        continue
    drawing = svg2rlg(src)
    renderPDF.drawToFile(drawing, dst)
    print(f"Converted {src} -> {dst}")
