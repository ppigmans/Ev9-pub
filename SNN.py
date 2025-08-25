import torch
import torch.nn as nn
import snntorch as snn
from snntorch import surrogate
import json
import os
from transformers import pipeline
from flask import Flask, request, jsonify

spike_grad = surrogate.fast_sigmoid(slope=25)

class RealCognitiveAppraisalModule:
    def __init__(self, output_dim, device='cpu'):
        self.output_dim = output_dim
        self.device = device
        pipeline_device = 0 if torch.cuda.is_available() and device!='cpu' else -1
        self.sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model="cardiffnlp/twitter-roberta-base-sentiment-latest",
            device=pipeline_device
        )

    def process_event(self, event_text):
        event_text = event_text[:2000] 
        try:
            sentiments = self.sentiment_pipeline(event_text, truncation=True)[0]
        except Exception as e:
            return self._generate_stimuli(0.1, 0.1, 0.1)

        score = sentiments['score']
        label = sentiments['label']

        if label == 'positive':
            pos_score, neg_score = score, 1 - score
        elif label == 'negative':
            pos_score, neg_score = 1 - score, score
        else:
            pos_score, neg_score = 0.1, 0.1

        distress_val = neg_score * 0.5
        return self._generate_stimuli(pos_score, neg_score, distress_val)

    def _generate_stimuli(self, pos_score, neg_score, distress_val):
        pleasure_val = pos_score - neg_score
        arousal_val = (pos_score + neg_score) * 0.8
        dominance_val = neg_score * 0.7
        return {
            'pleasure': torch.full((1, self.output_dim), pleasure_val, device=self.device),
            'arousal': torch.full((1, self.output_dim), arousal_val, device=self.device),
            'dominance': torch.full((1, self.output_dim), dominance_val, device=self.device),
            'distress': torch.full((1, self.output_dim), distress_val, device=self.device)
        }

class IntegratedEmotionalCoreSNN(nn.Module):
    def __init__(self, name, ocean_traits, device='cpu'):
        super().__init__()
        self.name = name
        self.device = device
        self.n_neurons = 400
        self.ocean = ocean_traits
        self.ocean_learning_rate = 0.0001
        self.update_snn_parameters()
        self.fc_pleasure = nn.Linear(self.n_neurons, self.n_neurons)
        self.fc_arousal = nn.Linear(self.n_neurons, self.n_neuro
