"""MLflow pyfunc wrapper so every task model is stored in the registry the same way (owner: M3).

The registry holds a pyfunc whose artifact is the joblib file of a TextScorer
or LangId. Serving loads it with `mlflow.pyfunc.load_model(...)` and calls
`unwrap_python_model().impl` to get the original object back.
"""

from __future__ import annotations

import joblib
import mlflow.pyfunc
import pandas as pd


class ModeraGuardPyfunc(mlflow.pyfunc.PythonModel):
    def load_context(self, context) -> None:
        self.impl = joblib.load(context.artifacts["model"])

    def predict(self, context, model_input, params=None):
        texts = model_input["text"].astype(str).tolist() if isinstance(model_input, pd.DataFrame) else list(model_input)
        if hasattr(self.impl, "score"):
            return pd.DataFrame({"score": self.impl.score(texts)})
        detected = self.impl.detect(texts)
        return pd.DataFrame({"language": [d[0] for d in detected], "confidence": [d[1] for d in detected]})
