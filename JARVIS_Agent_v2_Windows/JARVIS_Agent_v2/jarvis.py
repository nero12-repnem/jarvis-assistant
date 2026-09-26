import os, sys, re, time, sqlite3, datetime, webbrowser, subprocess, threading
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv

try:
    import pyaudiowpatch as pyaudio
    sys.modules["pyaudio"] = pyaudio
except Exception: pass

import speech_recognition as sr
import customtkinter as ctk
import pyttsx3, pyautogui, psutil, requests

BASE=Path(__file__).resolve().parent
load_dotenv(BASE/".env")
DATA=BASE/"data"; DATA.mkdir(exist_ok=True)
SHOTS=BASE/"screenshots"; SHOTS.mkdir(exist_ok=True)
DB=DATA/"jarvis.db"
AI_PROVIDER=os.getenv("AI_PROVIDER","auto").lower()
active=False
voice_lock=threading.Lock()
APP_INDEX={}

SYSTEM="""Você é o cérebro do JARVIS, assistente pessoal local do Windows.
Responda em português brasileiro, de forma objetiva e natural.
O programa local possui ferramentas do Windows. Nunca afirme que executou algo se a ferramenta local não executou."""

def conn(): return sqlite3.connect(DB)
def initdb():
    with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS memories(k TEXT PRIMARY KEY,v TEXT)")
def memtext():
    with conn() as c: rows=c.execute("SELECT k,v FROM memories").fetchall()
    return "\n".join(f"{k}: {v}" for k,v in rows) or "Nenhuma."
def ctx(q): return f"{SYSTEM}\nMemórias:\n{memtext()}\nUsuário: {q}"

# ---------- MULTI AI ----------
def gemini(q):
    from google import genai
    key=os.getenv("GEMINI_API_KEY","").strip()
    if not key: raise RuntimeError("GEMINI_API_KEY ausente")
    c=genai.Client(api_key=key); model=os.getenv("GEMINI_MODEL","gemini-3.6-flash")
    try:
        r=c.interactions.create(model=model,input=ctx(q)); return r.output_text
    except AttributeError:
        r=c.models.generate_content(model=model,contents=ctx(q)); return r.text

def openai_ai(q):
    from openai import OpenAI
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key: raise RuntimeError("OPENAI_API_KEY ausente")
    r=OpenAI(api_key=key).responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6"),input=ctx(q))
    return r.output_text

def anthropic_ai(q):
    import anthropic
    key=os.getenv("ANTHROPIC_API_KEY","").strip()
    if not key: raise RuntimeError("ANTHROPIC_API_KEY ausente")
    r=anthropic.Anthropic(api_key=key).messages.create(
        model=os.getenv("ANTHROPIC_MODEL","claude-sonnet-4-6"),max_tokens=900,system=SYSTEM,
        messages=[{"role":"user","content":f"Memórias:\n{memtext()}\n\n{q}"}])
    return "".join(x.text for x in r.content if getattr(x,"type","")=="text")

def ollama(q):
    u=os.getenv("OLLAMA_URL","http://localhost:11434").rstrip("/")
    r=requests.post(u+"/api/generate",json={"model":os.getenv("OLLAMA_MODEL","llama3.2"),"prompt":ctx(q),"stream":False},timeout=120)
    r.raise_for_status(); return r.json().get("response","")

AI_FUNCS={"gemini":gemini,"openai":openai_ai,"anthropic":anthropic_ai,"ollama":ollama}
def ask_ai(q):
    order=[AI_PROVIDER] if AI_PROVIDER!="auto" else [x.strip() for x in os.getenv("AI_FALLBACK_ORDER","gemini,openai,anthropic,ollama").split(",")]
    for name in order:
        if name not in AI_FUNCS: continue
        env={"gemini":"GEMINI_API_KEY","openai":"OPENAI_API_KEY","anthropic":"ANTHROPIC_API_KEY"}.get(name)
        if AI_PROVIDER=="auto" and env and not os.getenv(env,"").strip(): continue
        try:
            set_status("PENSANDO • "+name.upper()); ans=AI_FUNCS[name](q)
            if ans:
                ui(lambda n=name: provider.configure(text="IA ATIVA: "+n.upper()))
                return ans.strip()
        except Exception as e:
            print(f"Erro {name.upper()}:",e); time.sleep(1)
    return "Nenhum núcleo de IA respondeu agora, Senhor."

# ---------- APP DISCOVERY ----------
def norm(s):
    s=s.lower()
    s=re.sub(r"\.(lnk|url|exe|appref-ms)$","",s)
    s=re.sub(r"[^a-z0-9áàâãéêíóôõúç +#.-]"," ",s)
    return " ".join(s.split())

def index_apps():
    global APP_INDEX
    roots=[]
    pd=os.getenv("ProgramData")
    ad=os.getenv("APPDATA")
    home=Path.home()
    if pd: roots.append(Path(pd)/"Microsoft/Windows/Start Menu/Programs")
    if ad: roots.append(Path(ad)/"Microsoft/Windows/Start Menu/Programs")
    roots += [home/"Desktop", home/"OneDrive/Desktop"]
    idx={}
    for root in roots:
        if not root.exists(): continue
        try:
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".lnk",".url",".exe",".appref-ms"):
                    n=norm(p.stem)
                    if n and n not in ("uninstall","desinstalar","readme","help"):
                        idx.setdefault(n,[]).append(str(p))
        except Exception: pass
    # Aliases úteis para launchers/protocolos
    idx.setdefault("valorant",[]).append("__VALORANT__")
    idx.setdefault("riot client",[]).append("__RIOT__")
    APP_INDEX=idx
    ui(lambda: app_count.configure(text=f"APLICATIVOS INDEXADOS: {sum(len(v) for v in idx.values())}"))
    print("Aplicativos indexados:",len(idx))

def score(query,name):
    q=norm(query); n=norm(name)
    if q==n:return 100
    if n.startswith(q) or q.startswith(n):return 85
    if q in n:return 75
    qs=set(q.split()); ns=set(n.split())
    return int(60*len(qs&ns)/max(1,len(qs))) if qs&ns else 0

def launch_special(target):
    if target=="__VALORANT__":
        candidates=[
            Path(os.getenv("ProgramData","C:/ProgramData"))/"Microsoft/Windows/Start Menu/Programs/Riot Games/VALORANT.lnk",
            Path.home()/"Desktop/VALORANT.lnk",
            Path.home()/"OneDrive/Desktop/VALORANT.lnk"
        ]
        for p in candidates:
            if p.exists(): os.startfile(p); return True
        # Riot Client supports product launch arguments on common installs.
        for base in (os.getenv("ProgramFiles"),os.getenv("ProgramFiles(x86)")):
            if not base: continue
            exe=Path(base)/"Riot Games/Riot Client/RiotClientServices.exe"
            if exe.exists():
                subprocess.Popen([str(exe),"--launch-product=valorant","--launch-patchline=live"])
                return True
        return False
    if target=="__RIOT__":
        for base in (os.getenv("ProgramFiles"),os.getenv("ProgramFiles(x86)")):
            if base:
                exe=Path(base)/"Riot Games/Riot Client/RiotClientServices.exe"
                if exe.exists(): subprocess.Popen([str(exe)]); return True
        return False
    return False

def find_and_open_app(query):
    if not APP_INDEX:index_apps()
    ranked=[]
    for name,paths in APP_INDEX.items():
        s=score(query,name)
        if s>=45:
            for p in paths: ranked.append((s,name,p))
    ranked.sort(reverse=True,key=lambda x:x[0])
    if not ranked:
        # Fallback Windows shell search/start
        try:
            subprocess.Popen(["cmd","/c","start","",query],shell=False)
            return f"Tentei iniciar {query}, Senhor."
        except: return f"Não encontrei {query} entre os aplicativos instalados."
    s,name,target=ranked[0]
    try:
        if target.startswith("__"):
            ok=launch_special(target)
            return f"Abrindo {name}, Senhor." if ok else f"Encontrei {name}, mas não localizei o executável/atalho."
        os.startfile(target)
        return f"Abrindo {name}, Senhor."
    except Exception as e:
        return f"Encontrei {name}, mas não consegui iniciar: {e}"

# ---------- LOCAL TOOLS ----------
SITES={"youtube":"https://youtube.com","google":"https://google.com","github":"https://github.com",
       "gmail":"https://mail.google.com","drive":"https://drive.google.com","calendar":"https://calendar.google.com",
       "spotify":"https://open.spotify.com","chatgpt":"https://chatgpt.com"}

def process(raw):
    c=re.sub(r"^(ei\s+)?jarvis[,\s:;-]*","",raw.lower().strip()).strip()
    if not c:return "À disposição, Senhor."
    if "que horas" in c:return "São "+datetime.datetime.now().strftime("%H:%M")+"."
    if "bateria" in c:
        b=psutil.sensors_battery(); return f"Bateria em {round(b.percent)} por cento." if b else "Bateria não detectada."

    if "youtube" in c or ("vídeo" in c and any(x in c for x in ("pesquis","procur","busc","ache"))):
        q=c
        for x in ("pesquise para mim","pesquise","procure","busque","ache","no youtube","um vídeo","o vídeo","vídeo","por favor"):q=q.replace(x," ")
        q=" ".join(q.split()); webbrowser.open("https://youtube.com/results?search_query="+quote_plus(q))
        return f"Pesquisando {q} no YouTube."

    if any(x in c for x in ("pesquise no google","pesquise na internet","procure no google")):
        q=re.sub(r"pesquise no google|pesquise na internet|procure no google","",c).strip()
        webbrowser.open("https://google.com/search?q="+quote_plus(q)); return f"Pesquisando {q}."

    for n,u in SITES.items():
        if ("abra "+n) in c or ("acesse "+n) in c:
            webbrowser.open(u); return f"Abrindo {n}."

    # Descoberta automática: "abra/inicie/execute X"
    m=re.match(r"(?:abra|abrir|inicie|iniciar|execute|executar)\s+(?:o\s+|a\s+)?(.+)",c)
    if m:
        target=m.group(1).strip()
        folder_map={"downloads":Path.home()/"Downloads","documentos":Path.home()/"Documents",
                    "desktop":Path.home()/"Desktop","área de trabalho":Path.home()/"Desktop"}
        if target in folder_map:
            os.startfile(folder_map[target]); return f"Abrindo {target}."
        return find_and_open_app(target)

    if c in ("atualize aplicativos","reindexe aplicativos","reindexar aplicativos"):
        index_apps(); return "Índice de aplicativos atualizado."

    if "aumente o volume" in c:
        [pyautogui.press("volumeup") for _ in range(5)]; return "Volume aumentado."
    if "abaixe o volume" in c or "diminua o volume" in c:
        [pyautogui.press("volumedown") for _ in range(5)]; return "Volume diminuído."
    if "tire um print" in c or "screenshot" in c:
        p=SHOTS/("print_"+datetime.datetime.now().strftime("%Y%m%d_%H%M%S")+".png")
        pyautogui.screenshot().save(p); return f"Print salvo em {p.name}."

    m=re.match(r"lembre (?:que )?meu (.+?) é (.+)",c)
    if m:
        with conn() as d:d.execute("INSERT INTO memories VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(m.group(1),m.group(2)))
        return "Memória registrada."

    if any(x in c for x in ("desligue o computador","reinicie o computador","formate o computador","apague todos os arquivos")):
        return "Ação crítica bloqueada. Não executo operações destrutivas automaticamente."

    return ask_ai(raw)

# ---------- VOICE/UI ----------
def ui(fn):
    try:app.after(0,fn)
    except:pass
def set_status(t):ui(lambda:status.configure(text=t))
def log(a,t):
    def f():
        chat.configure(state="normal");chat.insert("end",f"\n{a}: {t}\n");chat.see("end");chat.configure(state="disabled")
    ui(f)
def speak(t):
    log("JARVIS",t);print("JARVIS:",t);set_status("FALANDO")
    with voice_lock:
        try:
            e=pyttsx3.init();e.setProperty("rate",180);e.say(t);e.runAndWait();e.stop()
        except Exception as x:print("TTS:",x)
    set_status("SISTEMA EM ESPERA")
def worker(t):speak(process(t))
def send(event=None):
    t=entry.get().strip()
    if not t:return
    entry.delete(0,"end");log("VOCÊ",t);threading.Thread(target=worker,args=(t,),daemon=True).start()
def listenloop():
    global active
    r=sr.Recognizer()
    while active:
        try:
            set_status("OUVINDO")
            with sr.Microphone() as s:
                r.adjust_for_ambient_noise(s,duration=.2);a=r.listen(s,timeout=7,phrase_time_limit=18)
            t=r.recognize_google(a,language="pt-BR");log("VOCÊ",t);worker(t)
        except (sr.WaitTimeoutError,sr.UnknownValueError):pass
        except Exception as e:print("MIC:",e)
def toggle():
    global active
    active=not active;mic.configure(text="■" if active else "🎙")
    if active:threading.Thread(target=listenloop,daemon=True).start()

initdb();ctk.set_appearance_mode("dark")
app=ctk.CTk();app.title("JARVIS Agent v2 • App Discovery");app.geometry("780x820")
ctk.CTkLabel(app,text="J A R V I S",font=("Consolas",32,"bold")).pack(pady=(25,3))
ctk.CTkLabel(app,text="AGENT v2 • MULTI-AI • WINDOWS APP DISCOVERY").pack()
status=ctk.CTkLabel(app,text="SISTEMA EM ESPERA",font=("Consolas",13,"bold"));status.pack(pady=8)
provider=ctk.CTkLabel(app,text="IA ATIVA: AUTO");provider.pack()
app_count=ctk.CTkLabel(app,text="APLICATIVOS INDEXADOS: CARREGANDO...");app_count.pack(pady=4)
mic=ctk.CTkButton(app,text="🎙",font=("Arial",26),width=90,height=90,corner_radius=45,command=toggle);mic.pack(pady=18)
chat=ctk.CTkTextbox(app,width=680,height=350);chat.pack(padx=20,pady=10)
chat.insert("end","JARVIS AGENT v2 ONLINE\nIndexando aplicativos do Windows...\n");chat.configure(state="disabled")
f=ctk.CTkFrame(app,fg_color="transparent");f.pack(fill="x",padx=50,pady=10)
entry=ctk.CTkEntry(f,placeholder_text="Ex.: Jarvis, abra o Valorant",height=42);entry.pack(side="left",fill="x",expand=True,padx=(0,8));entry.bind("<Return>",send)
ctk.CTkButton(f,text="ENVIAR",height=42,command=send).pack(side="right")
threading.Thread(target=index_apps,daemon=True).start()
app.mainloop()
