"""Запуск рендера битвы в GitHub Actions и скачивание готового ролика.

    python3 make.py fights/<id>.json [--preview]

Отправляет изменения в репозиторий, запускает workflow «Render», ждёт и кладёт ролик в output/<id>.mp4.
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


def sh(*cmd, check=True):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"{' '.join(cmd[:3])}: {(r.stderr or r.stdout)[-600:]}")
    return r.stdout.strip()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main():
    path = sys.argv[1]
    preview = "--preview" in sys.argv
    fid = json.load(open(path, encoding="utf-8"))["id"]
    assert os.path.basename(path) == f"{fid}.json", "id в файле должен совпадать с именем файла"
    repo = sh("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")

    sh("git", "add", "-A")
    if sh("git", "status", "--porcelain"):
        sh("git", "commit", "-qm", f"Битва {fid}")
    sh("git", "push", "-q", "origin", "HEAD:main")

    before = sh("gh", "run", "list", "-w", "Render", "-L", "1", "--json", "databaseId", "-q", ".[0].databaseId", check=False)
    sh("gh", "workflow", "run", "render.yml", "-f", f"fight={fid}", "-f", f"preview={'true' if preview else 'false'}")
    run_id = None
    for _ in range(30):
        time.sleep(4)
        cur = sh("gh", "run", "list", "-w", "Render", "-L", "1", "--json", "databaseId", "-q", ".[0].databaseId", check=False)
        if cur and cur != before:
            run_id = cur
            break
    if not run_id:
        sys.exit("GitHub не запустил рендер")
    log(f"рендер: https://github.com/{repo}/actions/runs/{run_id}")
    t0 = time.time()
    while True:
        time.sleep(30)
        st = sh("gh", "run", "view", run_id, "--json", "status,conclusion", "-q", '.status+" "+.conclusion', check=False)
        if st.startswith("completed"):
            break
    log(f"готово за {(time.time() - t0) / 60:.1f} мин: {st}")
    out = os.path.join(ROOT, "output")
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, f".dl_{run_id}")
    sh("gh", "run", "download", run_id, "-n", f"video-{fid}", "-D", tmp, check=False)
    src = os.path.join(tmp, f"{fid}.mp4")
    if not os.path.exists(src):
        sys.exit(f"ролика нет — смотри лог: https://github.com/{repo}/actions/runs/{run_id}")
    dst = os.path.join(out, f"{fid}{'_preview' if preview else ''}.mp4")
    os.replace(src, dst)
    os.rmdir(tmp)
    log("ролик:", dst)


if __name__ == "__main__":
    main()
