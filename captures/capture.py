import frida, sys, time, datetime, os
target = sys.argv[1]  # pid or exe path
logf = open(sys.argv[2], 'a', buffering=1)
def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']; ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        extra = p.get('extra') or ''
        if p['tag'] == 'ready': logf.write(f"{ts} READY {extra}\n"); return
        if p['tag'] == 'OPEN':  logf.write(f"{ts} OPEN {extra}\n"); return
        hexs = p['hex']
        if len(hexs) % 2: hexs += '0'
        suffix = f"  [{extra}]" if extra else ''
        logf.write(f"{ts} {p['tag']} len={p['n']} {hexs}{suffix}\n")
    else:
        logf.write(str(msg) + "\n")
if target.isdigit():
    session = frida.attach(int(target))
    script = session.create_script(open('hook.js').read()); script.on('message', on_message); script.load()
else:
    pid = frida.spawn(target, cwd=os.path.dirname(target)); session = frida.attach(pid)
    script = session.create_script(open('hook.js').read()); script.on('message', on_message); script.load()
    frida.resume(pid)
logf.write("attached\n")
try:
    while True: time.sleep(1)
except KeyboardInterrupt: pass
