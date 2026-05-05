# Predicting Urban Traffic Congestion

## File Organization

This repository follows a structured naming convention aligned with the traffic congestion classification pipeline.

**General format:**

```
<project>_<stage>_<description>_<version>.<extension>
```
* project: sdcc_traffic
* stage: raw, target, features, model, fig, etc.
* description: brief explanation of contents
* version: version number (v1, v2, …)

For configuration files, it will be simplified down to

```
config_mlp_<version>.yaml
```

The repository folder structure is depicted below.

```md
├── data
│   ├── processed
│   └── raw 
├── docs
├── notebooks
├── outputs
    ├── figures
    └── models
```