#!/usr/bin/env python3
"""
hCaptcha Visual Solver v2 — CLIP-based image classification (100% local)

Strategies:
  1. Simple prompts ("Select all chairs") → direct CLIP text-image matching
  2. Relational prompts ("items commonly used with X") → identify example object,
     then match cells against related items from lookup table
  3. Complex prompts ("creatures that could shelter in X") → identify example,
     reason about affordances via expanded CLIP prompts

Usage:
    from infra.hcaptcha_solver import solve_hcaptcha
    token = solve_hcaptcha("https://site.com/page", display=":121")
"""
import json
import os
import subprocess
import sys
import time
import re
import platform
from pathlib import Path

SOLVER_JS = Path(__file__).parent / "hcaptcha_visual_solver.js"
MAX_RETRIES = 6
NAMESPACES = [""] if platform.system() == "Windows" else ["", "ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]

# ─── Common objects for CLIP identification ───────────────────────
COMMON_OBJECTS = [
    "dog", "cat", "bird", "fish", "horse", "cow", "sheep", "elephant", "lion",
    "tiger", "bear", "rabbit", "mouse", "frog", "snake", "turtle", "monkey",
    "chicken", "duck", "butterfly", "bee", "spider", "ant", "dolphin", "whale",
    "car", "truck", "bus", "bicycle", "motorcycle", "airplane", "boat", "train",
    "chair", "table", "sofa", "bed", "desk", "lamp", "clock", "mirror", "shelf",
    "bookshelf", "cabinet", "drawer", "wardrobe", "bench", "stool",
    "cup", "mug", "glass", "bottle", "plate", "bowl", "fork", "knife", "spoon",
    "pot", "pan", "kettle", "toaster", "blender", "microwave", "oven", "fridge",
    "shoe", "boot", "sandal", "hat", "cap", "helmet", "bag", "backpack",
    "umbrella", "sunglasses", "watch", "ring", "necklace", "gloves", "scarf",
    "shirt", "jacket", "coat", "pants", "dress", "skirt", "suit", "tie", "belt",
    "ball", "bat", "racket", "guitar", "piano", "drum", "violin", "trumpet",
    "phone", "laptop", "computer", "tablet", "camera", "television", "radio",
    "book", "newspaper", "pen", "pencil", "scissors", "ruler", "eraser",
    "key", "lock", "door", "window", "fence", "gate", "bridge", "stairs",
    "tree", "flower", "grass", "leaf", "bush", "cactus", "mushroom", "rock",
    "mountain", "river", "lake", "ocean", "beach", "island", "forest",
    "house", "building", "castle", "church", "tent", "cabin", "barn",
    "apple", "banana", "orange", "grape", "strawberry", "watermelon", "lemon",
    "bread", "cake", "pizza", "sandwich", "hamburger", "hotdog", "fries",
    "cookie", "donut", "ice cream", "chocolate", "cheese", "egg",
    "hammer", "wrench", "screwdriver", "saw", "drill", "shovel", "axe",
    "broom", "mop", "bucket", "basket", "box", "candle", "vase", "pillow",
    "blanket", "towel", "soap", "toothbrush", "comb", "brush",
    "fire", "smoke", "rain", "snow", "sun", "moon", "star", "cloud",
    "birdhouse", "doghouse", "fishbowl", "cage", "nest", "burrow", "den",
    "barn", "stable", "kennel", "aquarium", "terrarium", "beehive",
]

# ─── Relational lookup: what items are commonly used WITH each object ─────
RELATED_ITEMS = {
    "cup": ["saucer", "spoon", "tea", "coffee", "sugar", "milk", "teapot", "coaster"],
    "mug": ["spoon", "tea", "coffee", "sugar", "coaster", "teabag"],
    "coffee": ["cup", "mug", "sugar", "milk", "spoon", "cream", "filter", "pot"],
    "tea": ["cup", "teapot", "sugar", "honey", "spoon", "saucer", "kettle", "teabag"],
    "plate": ["fork", "knife", "spoon", "napkin", "food", "table"],
    "fork": ["plate", "knife", "spoon", "napkin", "food"],
    "knife": ["fork", "plate", "cutting board", "bread"],
    "computer": ["keyboard", "mouse", "monitor", "desk", "chair", "headphones"],
    "laptop": ["mouse", "charger", "desk", "bag", "headphones", "keyboard"],
    "phone": ["charger", "case", "headphones", "earbuds", "screen"],
    "camera": ["lens", "tripod", "memory card", "bag", "flash", "battery"],
    "guitar": ["pick", "amp", "case", "strap", "strings", "tuner", "cable"],
    "piano": ["bench", "sheet music", "metronome", "pedal"],
    "book": ["bookmark", "glasses", "lamp", "shelf", "pen", "desk"],
    "pen": ["paper", "notebook", "ink", "desk", "cap"],
    "pencil": ["paper", "eraser", "sharpener", "notebook", "ruler"],
    "shoe": ["sock", "lace", "insole", "shoehorn", "polish", "brush"],
    "boot": ["sock", "lace", "polish", "mud", "snow"],
    "bicycle": ["helmet", "pump", "lock", "light", "bell", "basket", "wheel"],
    "car": ["key", "fuel", "tire", "steering wheel", "seatbelt", "mirror"],
    "bed": ["pillow", "blanket", "sheet", "mattress", "alarm clock", "lamp"],
    "chair": ["table", "desk", "cushion", "lamp"],
    "table": ["chair", "plate", "glass", "candle", "cloth", "vase"],
    "umbrella": ["rain", "coat", "boots", "puddle"],
    "hat": ["head", "hair", "sun", "scarf"],
    "ball": ["bat", "glove", "net", "goal", "field", "player"],
    "hammer": ["nail", "wood", "board", "helmet", "toolbox"],
    "saw": ["wood", "board", "goggles", "gloves", "ruler"],
    "broom": ["dustpan", "mop", "bucket", "floor", "dirt"],
    "toothbrush": ["toothpaste", "cup", "sink", "mirror", "water"],
    "soap": ["water", "towel", "sink", "hands", "bubbles", "dish"],
    "candle": ["match", "lighter", "holder", "flame", "wax"],
    "key": ["lock", "door", "keychain", "ring"],
    "fish": ["water", "bowl", "aquarium", "rod", "net", "hook", "bait"],
    "dog": ["leash", "collar", "bone", "bowl", "ball", "bed", "treat"],
    "cat": ["bowl", "toy", "bed", "litter", "collar", "yarn", "mouse"],
    "bird": ["cage", "feeder", "nest", "seed", "perch", "water"],
    "flower": ["vase", "pot", "soil", "water", "sun", "garden", "bee"],
    "tree": ["leaf", "bird", "nest", "squirrel", "fruit", "shade", "roots"],
    "paintbrush": ["paint", "canvas", "palette", "easel", "water"],
    "paint": ["brush", "canvas", "palette", "easel", "roller"],
    "fire": ["wood", "match", "lighter", "smoke", "extinguisher", "water"],
    "tent": ["sleeping bag", "campfire", "flashlight", "rope", "stakes"],
    "bread": ["butter", "knife", "jam", "plate", "toaster", "wheat"],
    "cake": ["candle", "plate", "fork", "knife", "frosting", "birthday"],
    "pizza": ["oven", "plate", "cheese", "sauce", "cutter"],
    "ice cream": ["cone", "bowl", "spoon", "sprinkles", "cherry"],
    "egg": ["pan", "fork", "plate", "oil", "salt", "pepper", "toast"],
    "sandwich": ["bread", "plate", "napkin", "pickle", "chips"],
    "apple": ["tree", "knife", "plate", "basket", "pie"],
    "banana": ["peel", "plate", "monkey", "smoothie", "bowl"],
    "wine": ["glass", "bottle", "cork", "corkscrew", "cheese", "grape"],
    "beer": ["glass", "mug", "bottle", "opener", "foam"],
    "pillow": ["bed", "blanket", "sheet", "case", "sofa"],
    "lamp": ["bulb", "table", "desk", "shade", "switch", "plug"],
    "clock": ["wall", "battery", "time", "alarm", "hand"],
    "mirror": ["frame", "wall", "comb", "brush", "light"],
    "basket": ["fruit", "flower", "bread", "egg", "picnic"],
    "bucket": ["water", "mop", "sand", "handle", "sponge"],
    "rope": ["knot", "anchor", "pulley", "tent", "climb"],
    "nail": ["hammer", "wood", "wall", "screw", "board"],
    "screw": ["screwdriver", "drill", "bolt", "nut", "wood"],
    "glasses": ["case", "cloth", "nose", "book", "frame"],
    "sunglasses": ["sun", "beach", "case", "hat"],
    "backpack": ["book", "pen", "laptop", "bottle", "zipper", "strap"],
    "bag": ["handle", "strap", "zipper", "wallet", "keys"],
    "wallet": ["money", "card", "pocket", "keys", "coins"],
    "watch": ["wrist", "time", "strap", "battery", "hand"],
    "ring": ["finger", "box", "diamond", "wedding", "hand"],
}

# ─── Shelter/affordance lookups ─────────────────────────────────
# Which creatures could shelter in which objects
SHELTER_MAP = {
    "birdhouse": ["bird", "small bird", "sparrow", "wren"],
    "doghouse": ["dog", "puppy"],
    "kennel": ["dog", "puppy"],
    "barn": ["horse", "cow", "chicken", "pig", "cat", "mouse", "rat", "owl"],
    "stable": ["horse", "cow", "donkey"],
    "cage": ["bird", "hamster", "rabbit", "parrot", "rat", "mouse"],
    "fishbowl": ["fish", "goldfish"],
    "aquarium": ["fish", "turtle", "frog", "crab", "shrimp", "seahorse"],
    "terrarium": ["snake", "lizard", "frog", "turtle", "spider", "gecko"],
    "beehive": ["bee", "wasp"],
    "nest": ["bird", "eagle", "robin", "sparrow", "mouse"],
    "burrow": ["rabbit", "fox", "mole", "mouse", "groundhog", "badger"],
    "den": ["bear", "fox", "wolf", "lion"],
    "cave": ["bear", "bat", "lion", "wolf", "spider"],
    "tree": ["bird", "squirrel", "owl", "monkey", "koala", "cat"],
    "house": ["human", "person", "dog", "cat", "mouse", "rat", "spider"],
    "cabin": ["human", "person", "bear", "mouse", "deer"],
    "tent": ["human", "person", "dog", "ant", "spider", "mosquito"],
    "bush": ["rabbit", "bird", "snake", "lizard", "hedgehog", "mouse"],
    "log": ["ant", "beetle", "spider", "snake", "salamander", "centipede", "worm"],
    "rock": ["lizard", "snake", "spider", "scorpion", "crab", "snail"],
    "shell": ["hermit crab", "snail", "turtle"],
    "box": ["cat", "mouse", "rat", "hamster", "spider", "ant"],
    "basket": ["cat", "kitten", "puppy", "rabbit", "hamster"],
    "pot": ["mouse", "ant", "spider", "snail", "frog"],
    "shoe": ["mouse", "spider", "ant", "beetle", "cockroach"],
    "hat": ["mouse", "rabbit", "bird", "frog", "spider"],
    "bottle": ["ant", "spider", "beetle", "fly"],
    "cup": ["ant", "spider", "fly", "beetle", "ladybug"],
    "bucket": ["frog", "fish", "crab", "snail", "mouse", "rat"],
    "bag": ["cat", "kitten", "puppy", "mouse", "snake", "spider"],
    "drawer": ["mouse", "rat", "spider", "ant", "cockroach"],
    "flower": ["bee", "butterfly", "ladybug", "ant", "beetle", "caterpillar"],
    "mushroom": ["ant", "snail", "beetle", "caterpillar", "frog"],
    "leaf": ["caterpillar", "ant", "ladybug", "snail", "beetle", "spider"],
}

# Creatures list for CLIP classification
ALL_CREATURES = [
    "dog", "cat", "bird", "fish", "horse", "cow", "sheep", "pig", "chicken",
    "duck", "rabbit", "mouse", "rat", "frog", "snake", "turtle", "lizard",
    "spider", "ant", "bee", "butterfly", "beetle", "caterpillar", "snail",
    "worm", "fly", "mosquito", "dragonfly", "ladybug", "cockroach",
    "crab", "shrimp", "lobster", "octopus", "jellyfish", "starfish",
    "monkey", "bear", "lion", "tiger", "elephant", "giraffe", "zebra",
    "deer", "wolf", "fox", "squirrel", "hedgehog", "owl", "eagle",
    "penguin", "parrot", "flamingo", "bat", "whale", "dolphin", "seal",
    "hamster", "guinea pig", "ferret", "gecko", "salamander", "scorpion",
    "centipede", "mole", "badger", "groundhog", "koala", "kangaroo",
    "person", "human", "baby", "child",
]


def log(msg):
    print(f"[HCAP][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def identify_object_clip(image_path: str) -> str:
    """Use CLIP to identify what object is in the image. Returns best label."""
    if not image_path or not os.path.exists(image_path):
        return ""
    
    log(f"Identifying object in: {os.path.basename(image_path)}")
    
    # Build text prompts for all common objects
    labels_json = json.dumps(COMMON_OBJECTS)
    
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"""
import torch, json, sys
from transformers import CLIPProcessor, CLIPModel
from PIL import Image

model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)

labels = {labels_json}
img = Image.open("{image_path}").convert("RGB")

# Process in batches of 50 to avoid memory issues
best_label = ""
best_score = -1

for i in range(0, len(labels), 50):
    batch = labels[i:i+50]
    texts = [f"a photo of a {{l}}" for l in batch]
    inputs = proc(text=texts, images=img, return_tensors="pt", padding=True)
    inputs = {{k: v.to(device) for k, v in inputs.items()}}
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits_per_image[0]
        probs = logits.softmax(dim=0)
    for j, (label, score) in enumerate(zip(batch, probs.tolist())):
        if score > best_score:
            best_score = score
            best_label = label

print(json.dumps({{"label": best_label, "score": best_score}}))
"""],
            capture_output=True, timeout=45, cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", ".")),
        )
        
        stdout = result.stdout.decode().strip()
        if stdout:
            data = json.loads(stdout)
            label = data["label"]
            score = data["score"]
            log(f"Identified: '{label}' (score={score:.3f})")
            return label
    except Exception as e:
        log(f"Identify error: {e}")
    return ""


def classify_cells_direct(prompt: str, image_paths: list) -> list:
    """Direct CLIP classification for simple prompts like 'Select all chairs'."""
    # Extract target from prompt
    target = prompt.lower()
    for prefix in [
        "please click on all images containing", "please click each image containing",
        "select all images containing", "select all the", "choose all the",
        "click on all images of", "select all images of", "select all",
        "selecione todas as imagens de", "selecione todas as imagens contendo",
        "selecione todos os", "selecione todas as", "toque em todos os",
        "toque em todas as",
    ]:
        if target.startswith(prefix):
            target = target[len(prefix):].strip()
            break
    for art in ["a ", "an ", "the ", "um ", "uma ", "o ", "a "]:
        if target.startswith(art):
            target = target[len(art):]
    target = target.strip().rstrip(".")
    
    log(f"Direct classify target: '{target}'")
    paths_json = json.dumps([p for p in image_paths if p])
    
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"""
import torch, json, sys
from transformers import CLIPProcessor, CLIPModel
from PIL import Image

model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)

target = '''{target}'''
paths = {paths_json}
texts = [f"a photo of a {{target}}", f"a photo of something that is not a {{target}}", "an empty or irrelevant photo"]

results = []
for i, path in enumerate(paths):
    try:
        img = Image.open(path).convert("RGB")
        inputs = proc(text=texts, images=img, return_tensors="pt", padding=True)
        inputs = {{k: v.to(device) for k, v in inputs.items()}}
        with torch.no_grad():
            outputs = model(**inputs)
            probs = outputs.logits_per_image[0].softmax(dim=0)
            score = probs[0].item()
        results.append((i, score))
        print(f"  cell {{i}}: {{score:.3f}}", file=sys.stderr)
    except Exception as e:
        print(f"  cell {{i}}: error {{e}}", file=sys.stderr)
        results.append((i, 0.0))

selected = [i for i, s in results if s > 0.55]
if not selected:
    selected = [i for i, s in results if s > 0.45]
if not selected:
    results.sort(key=lambda x: x[1], reverse=True)
    selected = [i for i, s in results[:3]]

print(json.dumps(selected))
"""],
            capture_output=True, timeout=60, cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", ".")),
        )

        stdout = result.stdout.decode().strip()
        stderr = result.stderr.decode(errors="replace")
        for line in stderr.strip().split("\n"):
            if line.strip():
                log(f"  {line.strip()}")

        if stdout:
            return json.loads(stdout)
    except Exception as e:
        log(f"Classify error: {e}")
    return []


def classify_cells_relational(prompt: str, example_path: str, image_paths: list) -> list:
    """
    For relational prompts: identify example object, then match cells
    against related items or creatures.
    """
    # Identify what the example object is
    example_label = identify_object_clip(example_path) if example_path else ""
    
    if not example_label:
        log("Could not identify example, falling back to direct classification")
        return classify_cells_direct(prompt, image_paths)
    
    log(f"Example identified as: '{example_label}'")
    
    prompt_lower = prompt.lower()
    
    # Determine what kind of relationship the prompt asks about
    is_shelter = any(w in prompt_lower for w in [
        "abrigar", "shelter", "live in", "morar", "viver", "esconder", "hide",
        "fit in", "caber", "dentro",
    ])
    is_used_with = any(w in prompt_lower for w in [
        "usado com", "used with", "comumente", "commonly", "junto", "together",
        "acompanha", "goes with", "associated",
    ])
    is_creature = any(w in prompt_lower for w in [
        "criatura", "creature", "animal", "bicho", "ser vivo",
    ])
    
    if is_shelter or is_creature:
        # Look up what creatures could shelter in this object
        candidates = SHELTER_MAP.get(example_label, [])
        if not candidates:
            # Try broader matches
            for key, creatures in SHELTER_MAP.items():
                if key in example_label or example_label in key:
                    candidates = creatures
                    break
        
        if not candidates:
            # Generic: small creatures for small objects, larger for large objects
            candidates = ALL_CREATURES[:30]  # Use a broad set
        
        log(f"Shelter candidates for '{example_label}': {candidates[:10]}...")
        return classify_cells_against_labels(image_paths, candidates)
    
    elif is_used_with:
        # Items commonly used with the example
        candidates = RELATED_ITEMS.get(example_label, [])
        if not candidates:
            for key, items in RELATED_ITEMS.items():
                if key in example_label or example_label in key:
                    candidates = items
                    break
        
        if not candidates:
            log(f"No related items found for '{example_label}', using image similarity")
            return classify_cells_by_similarity(example_path, image_paths)
        
        log(f"Related items for '{example_label}': {candidates}")
        return classify_cells_against_labels(image_paths, candidates)
    
    else:
        # Unknown relationship — try image similarity
        log(f"Unknown relationship type, using image similarity")
        return classify_cells_by_similarity(example_path, image_paths)


def classify_cells_against_labels(image_paths: list, candidate_labels: list) -> list:
    """Classify each cell: is it one of the candidate labels?"""
    paths_json = json.dumps([p for p in image_paths if p])
    labels_json = json.dumps(candidate_labels)
    
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"""
import torch, json, sys
from transformers import CLIPProcessor, CLIPModel
from PIL import Image

model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)

paths = {paths_json}
candidates = {labels_json}

# Build positive and negative text prompts
pos_texts = [f"a photo of a {{c}}" for c in candidates]
neg_texts = ["a photo of a random object", "a photo of scenery", "a photo of nothing relevant"]
all_texts = pos_texts + neg_texts

results = []
for i, path in enumerate(paths):
    try:
        img = Image.open(path).convert("RGB")
        inputs = proc(text=all_texts, images=img, return_tensors="pt", padding=True)
        inputs = {{k: v.to(device) for k, v in inputs.items()}}
        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits_per_image[0]
            probs = logits.softmax(dim=0)
        
        # Sum probability of all candidate labels
        pos_prob = sum(probs[:len(pos_texts)].tolist())
        neg_prob = sum(probs[len(pos_texts):].tolist())
        
        # Best matching candidate
        best_idx = probs[:len(pos_texts)].argmax().item()
        best_label = candidates[best_idx]
        best_score = probs[best_idx].item()
        
        ratio = pos_prob / (neg_prob + 1e-6)
        results.append((i, pos_prob, ratio, best_label, best_score))
        print(f"  cell {{i}}: pos={{pos_prob:.3f}} ratio={{ratio:.2f}} best='{{best_label}}'({{best_score:.3f}})", file=sys.stderr)
    except Exception as e:
        print(f"  cell {{i}}: error {{e}}", file=sys.stderr)
        results.append((i, 0.0, 0.0, "", 0.0))

# Select cells where positive probability dominates
# Use ratio (pos/neg) > 1.5 as threshold
selected = [i for i, pos, ratio, lbl, sc in results if ratio > 1.5]

# If too many or too few, adjust
if len(selected) > 6:
    results.sort(key=lambda x: x[2], reverse=True)
    selected = [i for i, _, _, _, _ in results[:4]]
elif not selected:
    results.sort(key=lambda x: x[2], reverse=True)
    selected = [i for i, _, ratio, _, _ in results[:3] if ratio > 0.8]
    if not selected:
        selected = [results[0][0], results[1][0], results[2][0]]

print(json.dumps(selected))
"""],
            capture_output=True, timeout=60, cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", ".")),
        )

        stdout = result.stdout.decode().strip()
        stderr = result.stderr.decode(errors="replace")
        for line in stderr.strip().split("\n"):
            if line.strip():
                log(f"  {line.strip()}")

        if stdout:
            return json.loads(stdout)
    except Exception as e:
        log(f"Label classify error: {e}")
    return []


def classify_cells_by_similarity(example_path: str, image_paths: list) -> list:
    """Use CLIP image-to-image similarity (via shared embedding space)."""
    if not example_path or not os.path.exists(example_path):
        return []
    
    paths_json = json.dumps([p for p in image_paths if p])
    
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"""
import torch, json, sys
from transformers import CLIPProcessor, CLIPModel
from PIL import Image

model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)

# Get embedding of example
example_img = Image.open("{example_path}").convert("RGB")
ex_inputs = proc(images=example_img, return_tensors="pt")
ex_inputs = {{k: v.to(device) for k, v in ex_inputs.items()}}
with torch.no_grad():
    ex_emb = model.get_image_features(**ex_inputs)
    ex_emb = ex_emb / ex_emb.norm(dim=-1, keepdim=True)

paths = {paths_json}
results = []
for i, path in enumerate(paths):
    try:
        img = Image.open(path).convert("RGB")
        inputs = proc(images=img, return_tensors="pt")
        inputs = {{k: v.to(device) for k, v in inputs.items()}}
        with torch.no_grad():
            emb = model.get_image_features(**inputs)
            emb = emb / emb.norm(dim=-1, keepdim=True)
        sim = (ex_emb @ emb.T).item()
        results.append((i, sim))
        print(f"  cell {{i}}: sim={{sim:.3f}}", file=sys.stderr)
    except Exception as e:
        print(f"  cell {{i}}: error {{e}}", file=sys.stderr)
        results.append((i, 0.0))

# Select most similar (but not TOO similar — exact match might be the example itself)
results.sort(key=lambda x: x[1], reverse=True)
mean_sim = sum(s for _, s in results) / len(results) if results else 0
threshold = mean_sim + 0.05

selected = [i for i, s in results if s > threshold]
if len(selected) > 5:
    selected = [i for i, _ in results[:4]]
elif not selected:
    selected = [i for i, _ in results[:3]]

print(json.dumps(selected))
"""],
            capture_output=True, timeout=60, cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", ".")),
        )

        stdout = result.stdout.decode().strip()
        stderr = result.stderr.decode(errors="replace")
        for line in stderr.strip().split("\n"):
            if line.strip():
                log(f"  {line.strip()}")

        if stdout:
            return json.loads(stdout)
    except Exception as e:
        log(f"Similarity error: {e}")
    return []


def classify_images_clip(prompt: str, images: list, example: str = "") -> list:
    """Main dispatcher: pick strategy based on prompt type."""
    prompt_lower = prompt.lower()
    
    is_relational = any(w in prompt_lower for w in [
        "item mostrado", "shown item", "example", "exemplo",
        "comumente", "commonly", "usado com", "used with",
        "abrigar", "shelter", "criatura", "creature",
        "poderiam", "could", "associado", "associated",
    ])
    
    if is_relational and example:
        log(f"Using RELATIONAL strategy (example available)")
        return classify_cells_relational(prompt, example, images)
    elif is_relational and not example:
        log(f"Relational prompt but no example image, using direct classification")
        return classify_cells_direct(prompt, images)
    else:
        log(f"Using DIRECT classification strategy")
        return classify_cells_direct(prompt, images)


def solve_hcaptcha_single(url: str, display: str = ":121", ns: str = "", timeout_s: int = 120) -> str:
    """Uma tentativa de resolver hCaptcha."""
    ns_label = ns or "host"
    log(f"[{ns_label}] Opening {url}")

    env = os.environ.copy()
    env["DISPLAY"] = display
    env["HOME"] = os.environ.get("HOME", "/root")
    env["NODE_PATH"] = os.environ.get("NODE_PATH", "/root/node_modules")

    _home = os.environ.get("HOME", "/root")
    _node_path = os.environ.get("NODE_PATH", "/root/node_modules")
    if ns and platform.system() != "Windows":
        cmd = [
            "sudo", "-n", "ip", "netns", "exec", ns,
            "env", f"DISPLAY={display}", f"HOME={_home}",
            f"NODE_PATH={_node_path}",
            "node", str(SOLVER_JS), url,
        ]
    else:
        cmd = ["node", str(SOLVER_JS), url]

    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", ".")),
        )

        start = time.time()
        token = ""

        while time.time() - start < timeout_s:
            try:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue

                msg = json.loads(line.decode().strip())
                status = msg.get("status", "")

                if status == "auto_solved":
                    token = msg.get("token", "")
                    log(f"[{ns_label}] Auto-solved! {len(token)} chars")
                    break

                elif status == "solved":
                    token = msg.get("token", "")
                    log(f"[{ns_label}] Solved! {len(token)} chars")
                    break

                elif status == "challenge":
                    prompt = msg.get("prompt", "")
                    images = msg.get("images", [])
                    example = msg.get("example", "")
                    round_num = msg.get("round", 1)
                    log(f"[{ns_label}] Round {round_num} — '{prompt}', {len(images)} imgs, example={'yes' if example else 'no'}")

                    # CLIP classify
                    clicks = classify_images_clip(prompt, images, example)
                    if clicks:
                        response = json.dumps({"clicks": clicks}) + "\n"
                        proc.stdin.write(response.encode())
                        proc.stdin.flush()
                        log(f"[{ns_label}] Sent clicks: {clicks}")
                    else:
                        proc.stdin.write(b'{"clicks":[]}\n')
                        proc.stdin.flush()

                elif status in ("error", "failed"):
                    log(f"[{ns_label}] {status}: {msg.get('error', '?')}")
                    break

            except json.JSONDecodeError:
                continue
            except Exception as e:
                log(f"[{ns_label}] Read error: {e}")
                break

        try:
            proc.kill()
        except:
            pass

        try:
            stderr = proc.stderr.read().decode(errors="replace")
            for line in stderr.strip().split("\n"):
                if line.strip():
                    log(f"  {line.strip()}")
        except:
            pass

        return token

    except Exception as e:
        log(f"[{ns_label}] Error: {e}")
        return ""


def solve_hcaptcha(url: str, display: str = ":121") -> str:
    """Resolve hCaptcha com rotação de namespace."""
    for attempt in range(1, MAX_RETRIES + 1):
        ns = NAMESPACES[(attempt - 1) % len(NAMESPACES)]
        ns_label = ns or "host"
        log(f"[Attempt {attempt}/{MAX_RETRIES}] NS={ns_label}")

        token = solve_hcaptcha_single(url=url, display=display, ns=ns)
        if token:
            log(f"Success on attempt {attempt} via {ns_label}")
            return token

        # Kill orphan chrome between attempts
        try:
            subprocess.run(
                "for pid in $(ps aux | grep chrome | grep -v grep | grep -v profiles_v15 | awk '{print $2}'); do kill -9 $pid 2>/dev/null; done",
                shell=True, timeout=5,
            )
        except:
            pass

        delay = min(attempt * 2, 5)
        log(f"Failed via {ns_label}, rotating in {delay}s...")
        time.sleep(delay)

    log(f"ALL {MAX_RETRIES} attempts failed!")
    return ""


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="hCaptcha Visual Solver v2 (CLIP)")
    p.add_argument("url", help="URL with hCaptcha")
    p.add_argument("--display", default=":121")
    a = p.parse_args()

    token = solve_hcaptcha(a.url, display=a.display)
    if token:
        print(f"TOKEN ({len(token)} chars): {token[:80]}...")
    else:
        print("FAILED")
        sys.exit(1)
