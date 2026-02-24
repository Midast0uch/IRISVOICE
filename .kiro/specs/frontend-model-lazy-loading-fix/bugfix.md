# Bugfix Requirements Document

## Introduction

The IRIS Voice Tauri widget experiences severe memory spikes (7000+ MB) and extended freeze times (up to 16 minutes) during frontend startup in dev mode. The issue occurs when three large AI models (LFM Audio, LFM2-8B, and LFM2.5-Instruct) are being eagerly loaded during the frontend compilation and cache write process, rather than being lazy loaded on-demand. This causes the IDE to freeze and significantly impacts developer experience during development.

The models are stored in the `IRISVOICE/models/` directory and total over 7GB in size. The memory spike occurs after files are sent to the temp folder and the compilation begins, with no console errors but extensive file write cache operations.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the Tauri widget starts in dev mode (npm run dev:tauri) THEN the system loads all three AI models (LFM Audio 1.5B, LFM2-8B-A1B, LFM2.5-1.2B-Instruct) eagerly during frontend compilation

1.2 WHEN the frontend compilation begins and writes to cache THEN the system experiences a memory spike exceeding 7000MB

1.3 WHEN the models are being loaded during dev mode startup THEN the IDE freezes for up to 16 minutes during the file write cache process

1.4 WHEN Next.js builds the frontend bundle THEN the system includes or references the large model files in the build process causing excessive memory usage

1.5 WHEN the backend initializes via the lifespan manager THEN the LFM audio manager initialization is commented out but models may still be referenced by the frontend build

### Expected Behavior (Correct)

2.1 WHEN the Tauri widget starts in dev mode THEN the system SHALL NOT load any AI models until they are explicitly needed by user interaction

2.2 WHEN the frontend compilation begins THEN the system SHALL complete the build process without loading model files into memory

2.3 WHEN the models directory is present THEN the system SHALL exclude model files from the frontend build and cache process

2.4 WHEN a user triggers a feature requiring AI models (e.g., voice command, chat) THEN the system SHALL lazy load only the required model at that time

2.5 WHEN the backend initializes THEN the system SHALL defer all model initialization until the first request that requires them

### Unchanged Behavior (Regression Prevention)

3.1 WHEN AI models are eventually loaded on-demand THEN the system SHALL CONTINUE TO function correctly with the same model inference capabilities

3.2 WHEN the Tauri widget is built for production THEN the system SHALL CONTINUE TO bundle the application correctly without including model files

3.3 WHEN the backend receives a request requiring models THEN the system SHALL CONTINUE TO initialize and use the models correctly

3.4 WHEN users interact with the voice command or chat features THEN the system SHALL CONTINUE TO provide the same functionality after lazy loading

3.5 WHEN the application runs in production mode THEN the system SHALL CONTINUE TO maintain the same performance characteristics for model inference
