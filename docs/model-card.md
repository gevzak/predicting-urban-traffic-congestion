# Model Card: Traffic Congestion Prediction MLP

## Model Description
The Traffic Congestion Prediction MLP Model is a multi-layer perceptron classifier designed to categorize urban traffic flow into five distinct congestion levels. It utilizes a sequential architecture with two hidden layers of 64 and 32 units respectively, incorporating dropout for regularization to prevent overfitting. The model is implemented using the TensorFlow Keras API and is optimized using the Adam optimizer with sparse categorical cross-entropy as the loss function. It was developed to provide a robust baseline for traffic state estimation using SCOOT sensor data.

## Intended Use
This model is intended for use by traffic engineers and urban planners to monitor and predict real-time traffic congestion levels based on sensor data. It can assist in identifying bottlenecks in the South Dublin County Council (SDCC) traffic network and provide early warnings for traffic management systems. The primary application is for automated monitoring of SCOOT-derived traffic metrics to improve urban mobility. It serves as a tool for data-driven decision making in urban transportation management.

## Out-of-scope Uses
The model is not suitable for safety-critical autonomous driving applications where real-time sub-second latency and absolute numerical precision are required. It should not be used to predict traffic patterns in regions outside of South Dublin without retraining on local sensor data, as traffic behavior varies significantly by geography. Furthermore, the model is not designed for long-term multi-year traffic trend forecasting, as it was trained on a specific six-month period in 2022.

## Training Data
The model was trained on the "Traffic Flow Data Jan to June 2022 SDCC" dataset, which consists of high-resolution 15-minute interval measurements from traffic sensors across South Dublin. This dataset includes features such as traffic flow, degree of saturation, and temporal metadata like day of the week and hour of the day. The data is archived on Zenodo under the DOI [10.5281/zenodo.20365705](https://doi.org/10.5281/zenodo.20365705) as part of the project repository. The training set covers a representative period of typical urban traffic behavior during the first half of 2022.

## Evaluation Results
The model was evaluated using a held-out test set comprising 20% of the original data. Performance metrics show strong performance for the "Free Flow" class but indicate challenges with minority classes due to heavy class imbalance, despite the use of balanced class weights. The following table summarizes the performance across the five congestion levels using metrics derived from the normalized confusion matrix and precision-recall analysis.

| Congestion Level | Average Precision (AP) | Recall | AUC  | Estimated F1-score |
|:-----------------|:----------------------:|:------:|:----:|:------------------:|
| 0 (Free Flow)    |          1.00          |  0.82  | 0.96 |        0.90        |
| 1 (Low)          |          0.16          |  0.54  | 0.85 |        0.25        |
| 2 (Medium)       |          0.11          |  0.27  | 0.92 |        0.16        |
| 3 (High)         |          0.23          |  0.27  | 0.97 |        0.25        |
| 4 (Severe)       |          0.34          |  0.74  | 0.99 |        0.46        |

The metrics indicate that while the model is highly reliable at identifying free-flowing traffic, its precision for specific congestion levels is lower due to the extreme rarity of those events in the dataset.

## Limitations
The model's performance is heavily dependent on the quality and uptime of the SCOOT sensor network, and missing sensor data can lead to inaccurate predictions. While class-weighting was employed to mitigate the 93% "Free Flow" imbalance, the model still exhibits lower precision for moderate congestion levels. Additionally, the target labels were derived using heuristic quantile-based binning which may not perfectly reflect subjective human perceptions of congestion. The model may also fail to capture anomalous traffic events such as accidents or special public events that were not present in the training data.

## Ethical Considerations
The use of this model for traffic management must consider potential biases if sensor distribution is uneven across different socioeconomic neighborhoods. Data privacy is maintained as the source data consists of aggregated traffic counts and does not contain personally identifiable information (PII) about individual drivers. However, reliance on automated predictions should be balanced with human oversight to avoid unintended consequences in emergency response routing. Stakeholders should be aware that model predictions are probabilistic and should be used as one of several inputs for traffic management decisions.

## Licence
This model and its associated documentation are released under the MIT License, as specified in the project's root directory. This allows for open use, modification, and distribution, provided that the original copyright notice and permission notice are included. Users should also respect the CC-BY-4.0 license of the source traffic data from South Dublin County Council. The documentation itself is provided "as-is" without warranty of any kind regarding its accuracy or completeness.
