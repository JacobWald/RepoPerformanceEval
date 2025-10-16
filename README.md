# DevAnalytics — Quick Start (Steps 1–3)

This guide gets you from zero to a working local setup. It’s written for beginners and covers:
1) Installing tools  
2) Cloning the project  
3) Setting up Python (venv) and installing dependencies

---

## 1) Install the Required Tools (one-time)

### 🐍 Python (3.10+)
- Download: https://www.python.org/downloads/
- **Windows:** during install, check **“Add Python to PATH.”**

### 🔧 Git
- Download: https://git-scm.com/downloads

### 💻 VS Code (optional but recommended)
- Download: https://code.visualstudio.com/
- In VS Code, install the **Python** extension (by Microsoft).

---

## 2) Get the Project (Clone the Repository)

Open a terminal (PowerShell on Windows; Terminal on macOS/Linux) and run:

```bash
# Choose a folder where you keep code, then:
git clone https://github.com/JacobWald/RepoPerformanceEval 
cd RepoPerformanceEval
```

After these commands, you should be inside the RepoPerformanceEval folder.

## 3) Set Up Python for This Project

We’ll create a virtual environment so the project’s packages don’t interfere with other projects on your computer.

---

## 3.1 Create the virtual environment

A virtual environment is an isolated workspace for this specific 
project — it prevents package conflicts between different Python projects.

Run the following command inside your project folder:

```bash
python -m venv venv
```

This will create a new folder named venv/ in your project directory

## 3.2 Activate the virtual environment

Activation “turns on” the environment so that anything you install with pip stays inside it.

On Windows (PowerShell or Command Prompt):

```bash
venv\Scripts\activate
```

On macOS/Linux

```bash
source venv/bin/activate
```

Once activated, your terminal prompt should change to something like:

```scss
(venv) C:\Users\you\devanalytics>
```

That (venv) at the start means your environment is active.
Keep it active whenever you’re working on this project.

💡 If VS Code shows a popup saying
“A new environment has been created — do you want to select it for this workspace?”,
click Yes.

## 3.3 Install project dependencies

With (venv) active, install all the required Python libraries

```bash
pip install -r requirements.txt
```

## 4) Run the server

Simply run the following command:

```bash
python manage.py runserver
```