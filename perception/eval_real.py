"""Real-world sanity check for the trained FoldBot YOLOv8n model.

Why this exists: the training/validation sets (data/yolo) are 400/100 images
composited from the SAME 5 GrabCut garment cutouts, so the reported
mAP50=0.995 on val is measuring near-duplicate memorization, not real-world
generalization. The honest next step is to point best.pt at fresh photos she
takes herself -- clothes on the actual folding board, real lighting -- and see
what breaks.

Usage (run in the same environment where training ran, i.e. where ultralytics
is installed):

    python3 -m perception.eval_real --imgdir ~/foldbot-real-photos --out runs/eval_real

Inputs: a folder of jpg/png photos (no labels needed).
Outputs: annotated copies in --out, plus eval_real.csv with one row per
detection (image, class, conf, x1, y1, x2, y2), and a printed summary:
images processed, images with zero detections, mean confidence, and
per-class counts. Zero-detection images are the ones to look at first.
"""

import argparse
import csv
import os
import sys

try:
    from ultralytics import YOLO
except ImportError:
    sys.exit("ultralytics is not installed in this environment. "
             "Run this script in the same env you used for training.")

MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "data", "yolo_runs", "foldbot_nano",
                     "weights", "best.pt")

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--imgdir", required=True, help="folder of real photos")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=416)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    model = YOLO(os.path.abspath(MODEL))

    files = sorted(f for f in os.listdir(args.imgdir)
                   if f.lower().endswith(IMG_EXTS))
    if not files:
        sys.exit(f"no images found in {args.imgdir}")

    csv_path = os.path.join(args.out, "eval_real.csv")
    n_imgs = len(files)
    n_zero = 0
    confs = []
    cls_counts = {}

    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["image", "class", "conf", "x1", "y1", "x2", "y2"])
        for fname in files:
            src = os.path.join(args.imgdir, fname)
            r = model.predict(src, conf=args.conf, imgsz=args.imgsz,
                              verbose=False)[0]
            names = r.names
            n_det = 0
            for b in r.boxes:
                cls_id = int(b.cls)
                cname = names.get(cls_id, str(cls_id))
                conf = float(b.conf)
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                w.writerow([fname, cname, f"{conf:.3f}",
                            f"{x1:.1f}", f"{y1:.1f}",
                            f"{x2:.1f}", f"{y2:.1f}"])
                confs.append(conf)
                cls_counts[cname] = cls_counts.get(cname, 0) + 1
                n_det += 1
            if n_det == 0:
                n_zero += 1
            r.save(filename=os.path.join(args.out, fname))

    print(f"images: {n_imgs}, zero detections: {n_zero}")
    if confs:
        print(f"detections: {len(confs)}, mean conf: "
              f"{sum(confs)/len(confs):.3f}")
    print(f"per-class: {cls_counts}")
    print(f"annotated: {args.out}  csv: {csv_path}")
    if n_zero:
        print("look at the zero-detection images first -- "
              "those are your generalization failures.")


if __name__ == "__main__":
    main()
