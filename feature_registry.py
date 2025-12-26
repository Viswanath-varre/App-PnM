# feature_registry.py
import os
import re

def scan_user_templates(template_dir="templates"):
  """
  Scans only user_*.html templates for:
    - data-feature="user_page:feature" → parent features
    - data-subfeature="user_page:feature" → subfeatures (children)

  Returns structured dict like:
  {
    "user_asset_master": [
      {
        "key": "inline_edit",
        "label": "Inline Edit",
        "subfeatures": ["Edit Package", "Edit Activity"]
      },
      {
        "key": "download_excel",
        "label": "Download Excel",
        "subfeatures": []
      }
    ],
    "user_fuel_consumption": [...]
  }
  """
  feature_matrix = {}

  pattern_feature = re.compile(
    r'data-feature=["\']([\w\-:]+)["\'](?:[^>]*data-label=["\']([^"\']+)["\'])?'
  )
  pattern_subfeature = re.compile(
    r'data-subfeature=["\']([\w\-:]+)["\'](?:[^>]*data-label=["\']([^"\']+)["\'])?'
  )

  for root, _, files in os.walk(template_dir):
    for filename in files:
      # ✅ Only scan user_*.html pages
      if not filename.startswith("user_") or not filename.endswith(".html"):
        continue

      page_key = filename.replace(".html", "")
      path = os.path.join(root, filename)

      try:
        with open(path, "r", encoding="utf-8") as f:
          content = f.read()

        features = {}

        # --- Detect main features ---
        for match in pattern_feature.findall(content):
          feature_key = match[0]
          label = match[1] if len(match) > 1 and match[1] else None
          parts = feature_key.split(":")
          if len(parts) == 2:
            _, feature = parts
            features[feature] = {
              "key": feature,
              "label": label or feature.replace("_", " ").title(),
              "subfeatures": []
            }

        # --- Detect subfeatures ---
        for match in pattern_subfeature.findall(content):
          subfeature_key = match[0]
          label = match[1] if len(match) > 1 and match[1] else None
          parts = subfeature_key.split(":")
          if len(parts) == 2:
            _, parent_feature = parts
            if parent_feature not in features:
              features[parent_feature] = {
                "key": parent_feature,
                "label": parent_feature.replace("_", " ").title(),
                "subfeatures": []
              }
            features[parent_feature]["subfeatures"].append(
              label or "Unnamed Subfeature"
            )

        # Sort for stable output
        sorted_features = sorted(features.values(), key=lambda x: x["key"])
        for f in sorted_features:
          f["subfeatures"].sort()

        feature_matrix[page_key] = sorted_features

      except Exception as e:
        print(f"⚠️ Error reading {path}: {e}")

  return feature_matrix


# --- Manual test ---
if __name__ == "__main__":
  result = scan_user_templates()
  print("🔍 Detected User Features:")
  for page, features in result.items():
    print(f"\n📄 {page}:")
    for f in features:
      print(f"  ➤ {f['label']} ({f['key']})")
      for sf in f["subfeatures"]:
        print(f"     - {sf}")
