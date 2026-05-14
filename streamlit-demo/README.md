# Ghost Chimera Streamlit Demo

This is the optional judge-facing Streamlit landing page for hackathon forms
that require Streamlit, Replit, or Vercel.

It is intentionally safe for hosted judging. It shows the Ghost path selector,
personalization sources, tool domains, generated Ghost blueprint, and trust
boundary without exposing a real local machine, email account, shell, desktop,
or private repository.

## Run Locally

```bash
pip install -r streamlit-demo/requirements.txt
streamlit run streamlit-demo/streamlit_app.py
```

## Deploy On Streamlit Community Cloud

Use these settings:

```text
Repository: fernandogarzaaa/GHOST-Chimera
Branch: main
Main file path: streamlit-demo/streamlit_app.py
```

For the hackathon form, choose:

```text
Streamlit
```

In the description, state that Streamlit is the judge landing page and that
Vultr is the intended backend/system of record for the real Ghost Console.
