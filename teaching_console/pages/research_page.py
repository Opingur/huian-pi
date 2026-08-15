"""Count-only Ground Truth page."""
from __future__ import annotations
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from teaching_console.services.research_count_service import ResearchCountService
from teaching_console.services.research_store import ResearchStore
from teaching_console.services.research_vision_service import ResearchVisionService
from teaching_console.services.vision_teaching_service import VisionTeachingWorker


TYPE_LABELS = {"teaching": "教学练习", "formal": "正式研究"}

def experiment_list_rows(store):
    """UI-only projection; the UUID remains Treeview item data, not user text."""
    rows = []
    for experiment in store.list_experiments():
        completed, total = store.progress(experiment["id"])
        rows.append({"id": experiment["id"], "name": experiment["name"], "type": TYPE_LABELS.get(experiment["experiment_type"], experiment["experiment_type"]), "video": Path(experiment["video_path"]).name, "progress": f"{completed} / {total}" if total else "未生成", "created_at": experiment["created_at"].replace("T", " ")})
    return rows


class ResearchPage(ttk.Frame):
    def __init__(self, master, root_path: Path) -> None:
        super().__init__(master)
        self.root_path = root_path; self.store = ResearchStore(root_path); self.counts = ResearchCountService(self.store)
        self.worker = VisionTeachingWorker(ResearchVisionService(root_path)); self.experiment = None; self.video = None; self.tasks=[]; self.index=0; self.token=0; self.busy=False; self.closing=False; self._detect_id=None; self._next_after_detect=None
        self.gt=tk.StringVar(); self.note=tk.StringVar(); self.status=tk.StringVar(value="请新建或打开实验"); self.meta=tk.StringVar(); self.point=tk.StringVar(); self.result=tk.StringVar(); self.metrics=tk.StringVar(); self.jump=tk.StringVar()
        self._scroll(); self._build(); self.after(40,self._drain)
    def _scroll(self):
        self.canvas=tk.Canvas(self,highlightthickness=0); self.bar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview); self.canvas.configure(yscrollcommand=self.bar.set); self.canvas.pack(side='left',fill='both',expand=True); self.bar.pack(side='right',fill='y'); self.body=ttk.Frame(self.canvas,padding=12); self.window=self.canvas.create_window((0,0),window=self.body,anchor='nw'); self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all'))); self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width)); self.bind('<Enter>',lambda e:self.canvas.bind_all('<MouseWheel>',self._wheel,add='+')); self.bind('<Leave>',lambda e:self.canvas.unbind_all('<MouseWheel>'))
    def _wheel(self,e): self.canvas.yview_scroll(-int(e.delta/120 or (1 if e.delta<0 else -1)),'units'); return 'break'
    def _build(self):
        ttk.Label(self.body,text='研究记录 / Ground Truth',font=('Segoe UI',16,'bold')).pack(anchor='w'); ttk.Label(self.body,text='人工 Ground Truth：观察原始画面后独立记录真实人数。正式研究会先保存人工结果，再揭示系统结果。',wraplength=1050).pack(anchor='w')
        top=ttk.Frame(self.body);top.pack(fill='x',pady=8);ttk.Button(top,text='新建实验',command=self.new).pack(side='left');ttk.Button(top,text='打开已有实验',command=self.open).pack(side='left',padx=5);ttk.Button(top,text='导出研究数据',command=self.export).pack(side='left');ttk.Label(top,textvariable=self.status).pack(side='right')
        ttk.Label(self.body,textvariable=self.meta,wraplength=1050).pack(anchor='w'); body=ttk.Panedwindow(self.body,orient='horizontal');body.pack(fill='both',expand=True,pady=8);left,right=ttk.Frame(body),ttk.Frame(body);body.add(left,weight=3);body.add(right,weight=2);self.image=ttk.Label(left,text='选择实验后显示原始视频帧',anchor='center');self.image.pack(fill='both',expand=True); self._right(right)
        bottom=ttk.LabelFrame(self.body,text='研究统计',padding=8);bottom.pack(fill='x');ttk.Label(bottom,textvariable=self.metrics).pack(anchor='w'); key=ttk.Frame(bottom);key.pack(anchor='w',pady=5);ttk.Entry(key,textvariable=self.jump,width=10).pack(side='left');ttk.Button(key,text='跳转秒数',command=self.jump_time).pack(side='left',padx=4);ttk.Button(key,text='添加当前时刻为关键样本',command=self.key).pack(side='left')
    def _right(self,p):
        ttk.Label(p,text='当前实验点',font=('Segoe UI',12,'bold')).pack(anchor='w');ttk.Label(p,textvariable=self.point).pack(anchor='w');ttk.Label(p,textvariable=self.result,wraplength=380).pack(anchor='w',pady=5);ttk.Label(p,text='人工真实人数：').pack(anchor='w');ttk.Entry(p,textvariable=self.gt,width=12).pack(anchor='w');ttk.Label(p,text='备注：').pack(anchor='w');ttk.Entry(p,textvariable=self.note,width=38).pack(anchor='w');buttons=ttk.Frame(p);buttons.pack(anchor='w',pady=8);ttk.Button(buttons,text='上一实验点',command=lambda:self.show(self.index-1)).pack(side='left');ttk.Button(buttons,text='保存',command=self.save).pack(side='left',padx=3);ttk.Button(buttons,text='保存并下一个',command=lambda:self.save(True)).pack(side='left');ttk.Button(buttons,text='下一实验点',command=lambda:self.show(self.index+1)).pack(side='left',padx=3);ttk.Button(p,text='运行系统检测',command=self.detect).pack(anchor='w')
    def new(self):
        name=simpledialog.askstring('新建实验','实验名称：',parent=self)
        if not name:return
        video=filedialog.askopenfilename(parent=self,filetypes=(('视频','*.mp4 *.avi *.mov *.mkv'),))
        if not video:return
        kind=simpledialog.askstring('实验类型','输入 teaching（教学练习）或 formal（正式研究）：',parent=self,initialvalue='teaching')
        if kind not in ('teaching','formal'):return
        eid=self.store.create_experiment(name,video,kind,simpledialog.askstring('场景说明','场景说明：',parent=self) or ''); self.load(eid)
        if messagebox.askyesno('生成任务','是否生成默认人数标注任务？',parent=self): self.counts.generate_tasks(eid,*self._metadata(Path(video))[0:2]);self.load(eid)
    def open(self):
        dialog = tk.Toplevel(self); dialog.title("打开已有实验"); dialog.geometry("760x420"); dialog.transient(self.winfo_toplevel()); dialog.grab_set()
        frame = ttk.Frame(dialog, padding=12); frame.pack(fill="both", expand=True)
        rows = experiment_list_rows(self.store)
        if not rows:
            ttk.Label(frame, text="暂无已有实验，请先新建实验。").pack(anchor="w")
            ttk.Button(frame, text="取消", command=dialog.destroy).pack(anchor="e", pady=12)
            return
        columns = ("name", "type", "video", "progress", "created")
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        for key, label, width in (("name", "实验名称", 210), ("type", "实验类型", 100), ("video", "视频", 150), ("progress", "人数标注进度", 105), ("created", "创建时间", 160)):
            tree.heading(key, text=label); tree.column(key, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True); scrollbar.pack(side="left", fill="y")
        bottom = ttk.Frame(dialog, padding=(12, 0, 12, 12)); bottom.pack(fill="x")
        detail = tk.StringVar(value="选择一个实验后打开。")
        ttk.Label(bottom, textvariable=detail, wraplength=500).pack(side="left")
        def selected():
            item = tree.selection()
            if not item:
                messagebox.showinfo("打开已有实验", "请先选择一个实验。", parent=dialog); return
            self.load(tree.item(item[0], "tags")[0]); dialog.destroy()
        for row in rows:
            tree.insert("", "end", values=(row["name"], row["type"], row["video"], row["progress"], row["created_at"]), tags=(row["id"],))
        tree.bind("<Double-1>", lambda _event: selected())
        ttk.Button(bottom, text="打开", command=selected).pack(side="right")
        ttk.Button(bottom, text="取消", command=dialog.destroy).pack(side="right", padx=5)
    def _metadata(self,path):
        import cv2
        cap=cv2.VideoCapture(str(path));fps=cap.get(cv2.CAP_PROP_FPS) or 0;frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));cap.release()
        if not fps or not frames:raise ValueError('无法读取视频 metadata')
        return frames/fps,fps
    def load(self,eid):
        self.experiment=self.store.get_experiment(eid);self.tasks=self.store.annotations(eid);self.index=0;path=Path(self.experiment['video_path']);self.meta.set(f"实验：{self.experiment['name']}  | 类型：{self.experiment['experiment_type']}  | 视频：{path}")
        if not path.is_file():self.status.set('原始视频文件不存在；数据库内容仍可查看');return
        self._send('open_video',path)
    def _send(self,op,*args):self.token+=1;self.busy=True;self.worker.submit(self.token,op,*args)
    def _drain(self):
        if self.closing:return
        while True:
            try:r=self.worker.results.get_nowait()
            except queue.Empty:break
            if r.token!=self.token:continue
            self.busy=False
            if r.error:self.status.set('错误：'+r.error);continue
            if r.operation=='open_video':self.video=r.value;self.show(0)
            else:self.render(r.value)
        self.after(40,self._drain)
    def show(self,i):
        if not self.tasks or self.busy:return
        self.index=max(0,min(i,len(self.tasks)-1));a=self.tasks[self.index];self.gt.set('' if a['ground_truth_count'] is None else str(a['ground_truth_count']));self.note.set(a['note']);self.point.set(f"第 {self.index+1} / {len(self.tasks)} 个  |  时间：{a['video_time_seconds']:.2f} s  | 帧：{a['frame_index']}");self.result.set('正式研究：请先独立填写人工人数。' if self.experiment['experiment_type']=='formal' and a['ground_truth_count'] is None else (f"系统人数：{a['system_count']}；人工人数：{a['ground_truth_count']}；绝对误差：{a['absolute_error']}" if a['system_count'] is not None else ''));self._send('read_raw',a['frame_index']);self.refresh()
    def render(self,p):
        try:
            from PIL import Image,ImageTk
            im=Image.fromarray(p.frame_bgr[:,:,::-1]);im.thumbnail((640,420));self.photo=ImageTk.PhotoImage(im);self.image.configure(image=self.photo,text='')
        except Exception as e:self.image.configure(text=str(e),image='')
        if p.mode=='detect':
            target=self._detect_id or self.tasks[self.index]['id'];self.store.update_system_count(target,len(p.rows));self.tasks=self.store.annotations(self.experiment['id']);a=self.tasks[self.index];self.result.set(f"系统人数：{len(p.rows)}；人工人数：{a['ground_truth_count'] if a['ground_truth_count'] is not None else '—'}；绝对误差：{a['absolute_error'] if a['absolute_error'] is not None else '—'}");self.refresh()
            if self._next_after_detect is not None:
                target=self._next_after_detect;self._next_after_detect=None;self.show(target)
    def detect(self):
        if not self.tasks or self.busy:return
        a=self.tasks[self.index]
        if self.experiment['experiment_type']=='formal' and a['ground_truth_count'] is None:messagebox.showinfo('盲标模式','请先保存人工真实人数。',parent=self);return
        self._detect_id=a['id'];self._send('detect',a['frame_index'])
    def save(self,next=False):
        try:v=int(self.gt.get());assert v>=0 and str(v)==self.gt.get().strip()
        except:messagebox.showwarning('输入错误','人工真实人数必须是非负整数。',parent=self);return
        a=self.tasks[self.index];self.store.update_ground_truth(self.experiment['id'],a['sample_index'],v,self.note.get());self.tasks=self.store.annotations(self.experiment['id'])
        if self.experiment['experiment_type']=='formal':
            if next:self._next_after_detect=self.index+1
            self.detect()
        elif next:self.show(self.index+1)
        else:self.refresh()
    def refresh(self):
        m=self.counts.metrics(self.experiment['id']);self.metrics.set(f"任务总数：{m['total_tasks']}  已完成：{m['completed_ground_truth']}  可评价：{m['evaluated_samples']}  MAE：{m['mae'] if m['mae'] is not None else '暂无可统计 Ground Truth 数据'}  最大误差：{m['max_absolute_error']}  完全正确率：{m['exact_match_rate']}")
    def jump_time(self):
        try:t=float(self.jump.get());self._send('read_raw',int(round(t*self.video.fps)))
        except Exception:messagebox.showwarning('输入错误','请输入有效秒数。',parent=self)
    def key(self):
        if not self.video:return
        try:t=float(self.jump.get())
        except:t=self.tasks[self.index]['video_time_seconds'] if self.tasks else 0
        if self.counts.add_key_sample(self.experiment['id'],t,self.video.fps,note='关键样本') is None:messagebox.showinfo('关键样本','该时刻附近已经存在研究样本。',parent=self)
        self.tasks=self.store.annotations(self.experiment['id']);self.refresh()
    def export(self):
        if not self.experiment:return
        out=self.counts.export_experiment(self.experiment['id'],self.root_path/'validation'/'exports');messagebox.showinfo('导出完成',f"导出完成：\n{out.relative_to(self.root_path)}",parent=self)
    def close(self):self.closing=True;self.worker.close()
