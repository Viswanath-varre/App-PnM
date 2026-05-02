import os
import re

def scan_user_templates(template_dir="templates"):
    feature_matrix = {}

    pattern_feature = re.compile(
        r'data-feature=["\']([\w\-:]+)["\'](?:[^>]*data-label=["\']([^"\']+)["\'])?'
    )
    pattern_subfeature = re.compile(
        r'data-subfeature=["\']([\w\-:]+)["\'](?:[^>]*data-label=["\']([^"\']+)["\'])?'
    )

    for root, _, files in os.walk(template_dir):
        for filename in files:
            # ✅ Scan BOTH user_*.html and admin_*.html pages
            if not (filename.startswith("user_") or filename.startswith("admin_")):
                continue
            # Skip base layouts
            if "base" in filename:
                continue

            # Add the page to the list automatically based on its filename
            page_key = filename.replace(".html", "")
            if page_key not in feature_matrix:
                feature_matrix[page_key] = []

            path = os.path.join(root, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()

                features = {}

                # Detect parent features
                for match in pattern_feature.findall(content):
                    feature = match[0]
                    label = match[1] if len(match) > 1 and match[1] else None
                    if feature not in features:
                        features[feature] = {
                            "key": feature,
                            "label": label or feature.replace("_", " ").title(),
                            "subfeatures": []
                        }

                # Detect subfeatures
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

                sorted_features = sorted(features.values(), key=lambda x: x["key"])
                for f in sorted_features:
                    f["subfeatures"].sort()

                # If features were found, attach them to the page
                if sorted_features:
                    feature_matrix[page_key] = sorted_features

            except Exception as e:
                print(f"⚠️ Error reading {path}: {e}")

    return feature_matrix