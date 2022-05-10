# -*- coding: utf-8 -*-
"""
Training script to showcase the end-to-end training and evaluation script.
"""

import numpy as np
import pandas as pd
import logging
import datetime

import joblib
from joblib import load, dump

import os
from os.path import exists
from os import makedirs
from os import environ
from glob import glob

import librosa
from tensorflow.keras import models, layers
import tensorflow as tf
from tensorflow.python.keras import backend as K
from tensorflow.python.client import device_lib
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix

from unittest.mock import MagicMock

from ai_api_client_sdk.models.metric import Metric
from ai_api_client_sdk.models.metric_custom_info import MetricCustomInfo
from ai_api_client_sdk.models.metric_tag import MetricTag

from ai_core_sdk.resource_clients.metrics_client import MetricsCoreClient
rest_client_mock = MagicMock()
tracking = MetricsCoreClient(rest_client_mock)

from datetime import datetime
dateTimeObj = datetime.now()
timestampStr = dateTimeObj.strftime('%Y-%m-%dT%H:%M:%S.%f+00:00')

FORMAT = "%(asctime)s:%(name)s:%(levelname)s - %(message)s"
# Use filename="file.log" as a param to logging to log to a file
logging.basicConfig(format=FORMAT, level=logging.INFO)


class TrainInterface:
    def __init__(self) -> None:
        # Set the params for the training below
        self.tf_model = None
        self.dataset = None
        self.train, self.val, self.test = None, None, None
        self.X_train, self.X_validation, self.X_test = [],[],[]
        self.y_train, self.y_validation, self.y_test = [],[],[]
        self.target_classes = None
        self.model_name = "sound_classifier.pkl"
        self.output_path = environ["OUTPUT_PATH"]
        self.file_name = environ["DATA_SOURCE"]
        self.loss = None
        self.val_loss = None
        self.accuracy = None
        self.val_accuracy = None
        self.class_dict={}
        self.classes={}

    def acoustic_feature_computation( self, clip ):
        scale, sr = librosa.load(clip)
        mel_spectrogram = librosa.feature.melspectrogram(scale, 
                                                 sr, 
                                                 hop_length=512,
                                                 n_mels=64,
                                                 fmax=sr/2)
        log_mel = librosa.power_to_db(mel_spectrogram)
        MFCCs=librosa.feature.mfcc(scale, sr, n_mfcc=40, fmax=sr/2)
        acoustic_features=np.concatenate( (MFCCs,log_mel), axis =0)
        return acoustic_features
        

    def read_dataset(self) -> None:
        """
        Reads the images file from path
        """
        
        path=self.file_name+'/*/*'
        
        
        logging.info(f"{path}")
        
        clips=glob(path)
        self.dataset=pd.DataFrame(data={'path':clips,
                            'label':[ c.split('/')[-2]  for c in clips]} )
        
        self.dataset = self.dataset.sample(frac=1).reset_index(drop=True)
        self.target_classes = self.dataset["label"].unique()
        TC='LABELS: '+' '.join(self.target_classes)
        logging.info(TC)
        
        self.class_dict=dict(enumerate(self.target_classes ))
        self.classes = {v: k for k, v in self.class_dict.items()}
        self.dataset['class']=self.dataset['label'].apply(lambda x : self.classes[x])
        TC='CLASSES: '+' '.join([str(c) for c in self.dataset['class'].unique()])
        logging.info(TC)
        return None


    def split_dataset(self) -> None:
        """
        Split the dataset into train, validate and test

        Raises:
            Error: if dataset_train and dataset_test are not set
        """
        if self.dataset is None:
            raise Exception("Train or test data not set")

        #Change splitting proportions
        self.train, self.val = train_test_split(self.dataset, test_size=0.4, random_state=25)
        self.val, self.test = train_test_split(self.val, test_size=0.5, random_state=25)
        
        return None

    def compute_features(self) -> None:
 
        for i,r in self.train.iterrows():
            self.X_train.append(self.acoustic_feature_computation(r['path']))
            self.y_train.append(r['class'])
            
        for i,r in self.test.iterrows():
            self.X_test.append(self.acoustic_feature_computation(r['path']))
            self.y_test.append(r['class'])
 
        for i,r in self.val.iterrows():
            self.X_validation.append(self.acoustic_feature_computation(r['path']))
            self.y_validation.append(r['class'])
        
        return None 
    
    def prepare_model(self):
    
        initializer = tf.keras.initializers.GlorotUniform()
        
        input_shape=(104,65,1)
        self.tf_model = models.Sequential(name = "CNN2")
        
        # Block 1
        self.tf_model.add(layers.Conv2D(32, (4, 4),(2,2), activation='relu', input_shape=input_shape, kernel_initializer=initializer, name ='block1_cnn1'))
        self.tf_model.add(layers.BatchNormalization())
        self.tf_model.add(layers.Conv2D(32, (4, 4),(2,2), activation='relu', kernel_initializer=initializer, name ='block1_cnn2'))
        self.tf_model.add(layers.BatchNormalization())
        self.tf_model.add(layers.MaxPooling2D((2, 2), name ='block1_maxpool'))
        
        # FC layers
        self.tf_model.add(layers.Flatten())
        self.tf_model.add(layers.Dense(512, activation='relu',kernel_initializer=initializer,name='FC1' ))
        self.tf_model.add(layers.Dropout(0.5))
        self.tf_model.add(layers.Dense(64, activation='relu',kernel_initializer=initializer,name='FC2' ))
        self.tf_model.add(layers.Dropout(0.5))
        
        # Output
        self.tf_model.add(layers.Dense(3, activation='softmax'))
        
        
        return None


    def train_model(self) -> None:
        """
        Train and save the model
        """
        
        dev = device_lib.list_local_devices()
        print([x.name for x in dev ])
        print("Num GPUs Available: ", len(tf.config.list_physical_devices('GPU')))

        self.tf_model.compile(optimizer= "adam",
              loss =tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True), 
              metrics = ['accuracy'])
        #config = tf.compat.v1.ConfigProto(device_count = {'GPU': 1, 'CPU': 15}) 
        #sess = tf.compat.v1.Session(config=config) 
        #keras.backend.set_session(sess)

        
        history = self.tf_model.fit(
            x=np.array(self.X_train, np.float32), 
            y=np.array(self.y_train, np.float32), 
            validation_data = ( np.array(self.X_validation, np.float32),
                                np.array(self.y_validation, np.float32),
                                           ),        
            epochs = 5 #To be changed
        )

        self.loss = history.history['loss']
        self.val_loss = history.history['val_loss']
        self.accuracy = history.history['accuracy']
        self.val_accuracy = history.history['val_accuracy']

        return None


    def save_model(self) -> None:
        """
        Saves the model to the local path
        """
        
        logging.info(f"Writing tokenizer into {self.output_path}")
        if not exists(self.output_path):
            makedirs(self.output_path)
        # Save the Tokenizer and target classes to pickle file
        with open(f"{self.output_path}/{self.model_name}", "wb") as handle:
            dump([self.tf_model, self.target_classes], handle)

        return None


    def get_model(self) -> None:
        """
        Get the model if it is available locally
        """
        
        if exists(f"{self.output_path}/{self.model_name}"):
            logging.info(f"Loading classifier pipeline from {self.output_path}")
            with open(f"{self.output_path}/{self.model_name}", "rb") as handle:
                [self.tf_model, self.target_classes] = load(handle)
        else:
            logging.info(f"Model has not been trained yet!")

        return None


    def model_metrics(self):
        """
        Perform an inference on the model that was trained
        """
        if self.tf_model is None:
            self.get_model()

        infer_data = np.array(self.X_test, np.float32)
        infer_data_labels = np.array(self.y_test, np.float32)
        
        score = self.tf_model.evaluate(infer_data, infer_data_labels)
        #print("Accuracy: " + str(score[0]))

        metric =  {"name": "Model Accuracy",
            "value": float(score[1]),
            "labels":[{"name": "dataset", "value": "test set"}],
             "timestamp":timestampStr
         }
            
        #print(metric)
        tracking.log_metrics(metrics = [Metric.from_dict(metric)], artifact_name = "sound-metrics")

        training_metrics = [
                    {'loss': str(self.loss)},
                    {'val_loss': str(self.val_loss)},
                    {'accuracy': str(self.accuracy)},
                    {'val_accuracy': str(self.val_accuracy)}
                ]
        custom_info_1 = {"name": "Metrics", 
                          "value": str(training_metrics)}

        #print(custom_info_1)
        tracking.set_custom_info([MetricCustomInfo.from_dict(custom_info_1)])
        logging.info(f"custom_info_1")

        #confusion matrix
        pred=self.tf_model(np.array(self.X_test, np.float32) , training=False)
        pred_class = [ np.where(arr == np.amax(arr))[0][0] for arr in np.array(pred) ]
        pred_label = [ self.class_dict[i]  for i in pred_class]
        pred_confidence = [ np.max(arr) for arr in np.array(pred)]
        
        cf_matrix = confusion_matrix(self.y_test, pred_class)
        custom_info_2 = {'name': "confusion_matrix", 
                          "value": str({ 
                              'cf_matrix':  cf_matrix.tolist() ,\
                              'classes': [ k for k in self.classes.keys()]
                          })
                         } 

        #print(custom_info_2)
        tracking.set_custom_info([MetricCustomInfo.from_dict(custom_info_2)])
        logging.info(f"custom_info_2")


        return None


    def run_workflow(self) -> None:
        """
        Run the training script with all the necessary steps
        """
        logging.info(f"Let's gooo")
        
        self.read_dataset()
        logging.info(f"Data has been read")

        self.split_dataset()
        logging.info(f"Dataset has been split")

        self.compute_features()
        logging.info(f"Features has been extracted")

        
        self.get_model()
        if self.tf_model is None:
            # Train the model if no model is available
            logging.info(f"Training classifier and saving it locally")
            self.prepare_model()
            self.train_model()
            self.save_model()

        self.model_metrics()

        return None


if __name__ == "__main__":
    train_obj = TrainInterface()
    train_obj.run_workflow()
