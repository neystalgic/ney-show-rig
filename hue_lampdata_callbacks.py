# HUE RIG -- Script TOP callbacks: copies the engine's lamp data (16 x 2,
# positions and colours) into a tiny picture the preview shader can read.
import numpy as np

def onCook(scriptOp):
    data = scriptOp.parent().fetch('lampdata', None)
    if data is None:
        data = np.zeros((2, 16, 4), dtype=np.float32)
    scriptOp.copyNumpyArray(data)
    return

def onSetupParameters(scriptOp):
    return

def onPulse(par):
    return
