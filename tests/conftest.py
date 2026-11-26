import os

# tests never record to W&B
os.environ["KTIDE_WANDB"] = "0"
