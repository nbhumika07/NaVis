# NaVis

# NaVis-Desktop navigation assistant for visually impaired users
A keyboard-driven desktop navigation tool for visually impaired users on Windows.

NaVis is a Python-based assistive technology project that helps visually impaired users navigate graphical user interfaces through keyboard and mouse interactions with real-time speech feedback.

The system uses Windows UI Automation and pywinauto to detect and identify GUI elements such as buttons, menus, toolbars, application windows, and desktop icons, and converts this information into accessible navigation and audio feedback.

## About the Project

Interacting with graphical interfaces can be challenging for users who cannot rely on visual information. NaVis aims to provide an additional accessibility layer that helps users understand and navigate desktop interfaces through audio.

The system continuously monitors user interaction, identifies the GUI element being accessed, organizes detected elements for navigation, and provides speech feedback describing the element.

## How it works
```text
Keyboard / Mouse Interaction
            ↓
      GUI Element Detection
            ↓
     Element Identification
            ↓
      Navigation System
            ↓
       Speech Feedback
```

## Key Features
-Real-time GUI element detection
-Keyboard-based navigation
-Mouse interaction tracking
-Speech feedback for detected elements
-Virtual navigation structure
-Navigation history
-Support for Windows desktop applications

## Tech Stack
Python
Windows UI Automation
pywinauto
Keyboard & Mouse Listeners
Text-to-Speech
Windows APIs

## Requirements
- Python 3.10+
- pyttsx3, pynput, pywinauto

## Install dependencies
pip install pyttsx3 pynput pywinauto

## Run
python navis.py

## Keys
| Key | Action |
|-----|--------|
| R | Scan / refresh |
| H | Go to first item |
| ← → ↑ ↓ | Navigate grid |
| Enter×2 | Open file/folder |
| B / Backspace | Go back |
| V | Toggle hover mode |
| D | Detect element under cursor |
| F + word + Enter | Search by name |
| W | Full position info |
| P | Speak current path |
| S | Show suggestions |
| Q | Quit |
