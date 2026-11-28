import joblib, numpy as np, pandas as pd

prep = joblib.load("spc_model/preprocessor.joblib")
clf  = joblib.load("spc_model/classifier.joblib")
le   = joblib.load("spc_model/label_encoder.joblib")
FEATURES = joblib.load("spc_model/features.joblib")

X_new = pd.DataFrame([{
    'Nominal': 58.941176,
    'F': 12.56, 'R': 127.537, 'C0': 0.58, 'Cq': 0.18, 'Q': 114.07,
}])[FEATURES]

X_new_pp = prep.transform(X_new.to_numpy(dtype=np.float64))
y_pred   = clf.predict(X_new_pp)
spc      = le.inverse_transform(y_pred)

print("Predicted specification:", spc[0])

# также проверь top-3
proba = clf.predict_proba(X_new_pp)[0]
top3  = np.argsort(proba)[-3:][::-1]
print("Top-3 candidates:", [(le.classes_[i], round(float(proba[i]), 4)) for i in top3])