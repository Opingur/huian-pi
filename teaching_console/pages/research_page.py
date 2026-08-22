"""Count-only Ground Truth page."""
from __future__ import annotations
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from teaching_console.services.research_count_service import ResearchCountService
from teaching_console.services.research_prediction_analysis import AnalysisCancelled, PredictionTimelineAnalysis
from teaching_console.services.research_prediction_service import ResearchPredictionService
from teaching_console.services.research_store import ResearchStore
from teaching_console.services.research_vision_service import ResearchVisionService
from teaching_console.services.vision_teaching_service import VisionTeachingWorker
from teaching_console.runtime_paths import ensure_writable_data_root
from teaching_console.ui_zoom import CONTROL_MASK, scaled_value


TYPE_LABELS = {"teaching": "教学练习", "formal": "正式研究"}

def format_prediction_slope(value):
    """Render a prediction slope for the UI without changing stored data."""
    return "暂无数据" if value is None else f"{float(value):+.3f}"


def format_prediction_value(value):
    """Render a predicted people count for the UI without changing stored data."""
    return "暂无数据" if value is None else f"{float(value):.1f}"


def format_prediction_error(value):
    """Render one prediction absolute error for the UI."""
    return "暂无数据" if value is None else f"{float(value):.1f}"


def format_prediction_mae(value):
    """Render an aggregate prediction MAE for the UI."""
    return "暂无数据" if value is None else f"{float(value):.2f}"


def experiment_list_rows(store):
    """UI-only projection; the UUID remains Treeview item data, not user text."""
    rows = []
    for experiment in store.list_experiments():
        completed, total = store.progress(experiment["id"])
        rows.append({"id": experiment["id"], "name": experiment["name"], "type": TYPE_LABELS.get(experiment["experiment_type"], experiment["experiment_type"]), "video": Path(experiment["video_path"]).name, "progress": f"{completed} / {total}" if total else "未生成", "created_at": experiment["created_at"].replace("T", " ")})
    return rows


def prediction_target(anchor_time_seconds: float, horizon_seconds: int, fps: float) -> tuple[float, int]:
    target_time = float(anchor_time_seconds) + int(horizon_seconds)
    return target_time, int(round(target_time * fps))


BASE_VIDEO_SIZE = (640, 420)


class ResearchPage(ttk.Frame):
    def __init__(self, master, root_path: Path) -> None:
        super().__init__(master)
        self.root_path = root_path; self.data_root = ensure_writable_data_root(root_path); self.store = ResearchStore(self.data_root); self.counts = ResearchCountService(self.store); self.predictions = ResearchPredictionService(self.store)
        self.worker = VisionTeachingWorker(ResearchVisionService(root_path)); self._zoom_factor=1.0; self._count_frame_bgr=None; self._prediction_frame_bgr=None; self.experiment = None; self.video = None; self.tasks=[]; self.index=0; self.token=0; self.busy=False; self.closing=False; self._prediction_target=None; self._prediction_photo=None; self._detect_id=None; self._next_after_detect=None; self.mode=tk.StringVar(value="count"); self.pred_index=0; self.pred_rows=[]; self.analysis_events=queue.Queue(); self.cancel_analysis=None
        self.gt=tk.StringVar(); self.note=tk.StringVar(); self.status=tk.StringVar(value="请新建或打开实验"); self.meta=tk.StringVar(); self.point=tk.StringVar(); self.result=tk.StringVar(); self.metrics=tk.StringVar(); self.jump=tk.StringVar()
        self._scroll(); self._build(); self.after(40,self._drain)
    def _scroll(self):
        self.canvas=tk.Canvas(self,highlightthickness=0); self.bar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview); self.canvas.configure(yscrollcommand=self.bar.set); self.canvas.pack(side='left',fill='both',expand=True); self.bar.pack(side='right',fill='y'); self.body=ttk.Frame(self.canvas,padding=12); self.window=self.canvas.create_window((0,0),window=self.body,anchor='nw'); self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all'))); self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width)); self.bind('<Enter>',lambda e:self.canvas.bind_all('<MouseWheel>',self._wheel,add='+')); self.bind('<Leave>',lambda e:self.canvas.unbind_all('<MouseWheel>'))
    def _wheel(self,e):
        if e.state & CONTROL_MASK:return None
        self.canvas.yview_scroll(-int(e.delta/120 or (1 if e.delta<0 else -1)),'units'); return 'break'
    def _build(self):
        ttk.Label(self.body,text='研究记录 / Ground Truth',font=('Segoe UI',16,'bold')).pack(anchor='w'); modes=ttk.Frame(self.body);modes.pack(anchor='w',pady=(4,0));ttk.Radiobutton(modes,text='人数 Ground Truth',variable=self.mode,value='count',command=self.set_mode).pack(side='left');ttk.Radiobutton(modes,text='预测 Ground Truth',variable=self.mode,value='prediction',command=self.set_mode).pack(side='left',padx=12);ttk.Label(self.body,text='人工 Ground Truth：由观察者独立查看原始画面后记录真实人数。',wraplength=1050).pack(anchor='w');self.count_area=ttk.Frame(self.body);self.count_area.pack(fill='both',expand=True)
        top=ttk.Frame(self.count_area);top.pack(fill='x',pady=8);ttk.Button(top,text='新建实验',command=self.new).pack(side='left');ttk.Button(top,text='打开已有实验',command=self.open).pack(side='left',padx=5);ttk.Button(top,text='导出研究数据',command=self.export).pack(side='left');ttk.Label(top,textvariable=self.status).pack(side='right')
        ttk.Label(self.count_area,textvariable=self.meta,wraplength=1050).pack(anchor='w'); body=ttk.Panedwindow(self.count_area,orient='horizontal');body.pack(fill='both',expand=True,pady=8);left,right=ttk.Frame(body),ttk.Frame(body);body.add(left,weight=3);body.add(right,weight=2);self.image=ttk.Label(left,text='选择实验后显示原始视频帧',anchor='center');self.image.pack(fill='both',expand=True); self._right(right)
        bottom=ttk.LabelFrame(self.count_area,text='研究统计',padding=8);bottom.pack(fill='x');ttk.Label(bottom,textvariable=self.metrics).pack(anchor='w'); key=ttk.Frame(bottom);key.pack(anchor='w',pady=5);ttk.Entry(key,textvariable=self.jump,width=10).pack(side='left');ttk.Button(key,text='跳转秒数',command=self.jump_time).pack(side='left',padx=4);ttk.Button(key,text='添加当前时刻为关键样本',command=self.key).pack(side='left')
        self._build_prediction()

    def _build_prediction(self):
        self.pred_area=ttk.Frame(self.body, padding=(0,8)); self.pred_status=tk.StringVar(); self.pred_info=tk.StringVar(); self.pred_metrics=tk.StringVar(); self.pred_gt={h:tk.StringVar() for h in (10,20,30)}; self.pred_error={h:tk.StringVar(value="绝对误差：暂无数据") for h in (10,20,30)}
        ttk.Label(self.pred_area,text='预测 Ground Truth',font=('Segoe UI',13,'bold')).pack(anchor='w'); ttk.Label(self.pred_area,textvariable=self.pred_status,wraplength=1000).pack(anchor='w',pady=4); preview=ttk.LabelFrame(self.pred_area,text='Ground Truth 原始画面',padding=6);preview.pack(fill='both',expand=True,pady=4);self.pred_view_label=tk.StringVar(value='当前查看：尚未选择未来验证时刻');ttk.Label(preview,textvariable=self.pred_view_label).pack(anchor='w');self.pred_image=ttk.Label(preview,text='点击“查看原始画面”后显示目标帧',anchor='center');self.pred_image.pack(fill='both',expand=True)
        self.analyze_button=ttk.Button(self.pred_area,text='分析视频并生成预测实验点',command=self.start_prediction_analysis);self.analyze_button.pack(anchor='w'); self.cancel_button=ttk.Button(self.pred_area,text='取消分析',command=self.cancel_prediction_analysis); self.cancel_button.pack(anchor='w',pady=3)
        ttk.Label(self.pred_area,textvariable=self.pred_info,wraplength=1000).pack(anchor='w',pady=6); self.pred_form=ttk.Frame(self.pred_area);self.pred_form.pack(fill='x')
        for h in (10,20,30):
            row=ttk.LabelFrame(self.pred_form,text=f'+{h} 秒验证',padding=6);row.pack(fill='x',pady=3); ttk.Label(row,text=f'人工真实人数：').pack(side='left');ttk.Entry(row,textvariable=self.pred_gt[h],width=10).pack(side='left');ttk.Button(row,text='查看原始画面',command=lambda x=h:self.view_prediction_target(x)).pack(side='left',padx=5);ttk.Button(row,text='引用已有人数 Ground Truth',command=lambda x=h:self.reference_count_gt(x)).pack(side='left');ttk.Label(row,textvariable=self.pred_error[h]).pack(side='left',padx=8)
        nav=ttk.Frame(self.pred_area);nav.pack(anchor='w',pady=6);ttk.Button(nav,text='上一个预测点',command=lambda:self.show_prediction(self.pred_index-1)).pack(side='left');ttk.Button(nav,text='保存预测验证',command=self.save_prediction).pack(side='left',padx=4);ttk.Button(nav,text='保存并下一个预测点',command=lambda:self.save_prediction(True)).pack(side='left');ttk.Button(nav,text='下一个预测点',command=lambda:self.show_prediction(self.pred_index+1)).pack(side='left',padx=4);ttk.Label(self.pred_area,textvariable=self.pred_metrics,wraplength=1000).pack(anchor='w')
    def set_mode(self):
        if self.mode.get()=='prediction': self.count_area.pack_forget();self.pred_area.pack(fill='both',expand=True);self.refresh_prediction()
        else: self.pred_area.pack_forget();self._prediction_target=None;self.count_area.pack(fill='both',expand=True)
    def refresh_prediction(self):
        if not self.experiment:return
        self.pred_rows=self.store.prediction_annotations(self.experiment['id']);m=self.predictions.prediction_metrics(self.experiment['id']);self.pred_metrics.set(f"预测实验点：{m['prediction_anchor_count']}  完整验证：{m['completed_prediction_count']} / {m['prediction_anchor_count']}  | +10：{m['samples_10']}，MAE {format_prediction_mae(m['mae_10'])} 人  | +20：{m['samples_20']}，MAE {format_prediction_mae(m['mae_20'])} 人  | +30：{m['samples_30']}，MAE {format_prediction_mae(m['mae_30'])} 人")
        if self.pred_rows:self.show_prediction(self.pred_index)
        else:self.pred_status.set('当前实验尚未生成预测研究数据。预测需要连续分析视频，不能只随机查看一帧。')
    def show_prediction(self,index):
        if not self.pred_rows:return
        self.pred_index=max(0,min(index,len(self.pred_rows)-1));a=self.pred_rows[self.pred_index];done=all(a[f'gt_{h}'] is not None for h in (10,20,30));self.pred_status.set(f"预测验证：{self.pred_index+1} / {len(self.pred_rows)}  {'✓ 已完成' if done else '○ 未完成'}")
        self.pred_info.set(f"预测起点：{a['anchor_time_seconds']:.1f} s  | 当时系统人数：{a['current_system_count']}  | 趋势斜率：{format_prediction_slope(a['prediction_slope'])} 人/秒\n这些预测值是在预测起点产生并冻结保存的历史预测结果。\n+10：{format_prediction_value(a['prediction_10'])} 人  +20：{format_prediction_value(a['prediction_20'])} 人  +30：{format_prediction_value(a['prediction_30'])} 人")
        for h in (10,20,30):
            self.pred_gt[h].set('' if a[f'gt_{h}'] is None else str(a[f'gt_{h}']))
            self.pred_error[h].set(f"绝对误差：{format_prediction_error(a[f'error_{h}'])} 人")
    def start_prediction_analysis(self):
        if not self.experiment or self.cancel_analysis:return
        path=Path(self.experiment['video_path'])
        if not path.is_file():self.pred_status.set('原始视频文件不存在。');return
        self.cancel_analysis=threading.Event();self.analyze_button.state(['disabled']);self.pred_status.set('正在分析视频……')
        def run():
            try:
                timeline=PredictionTimelineAnalysis(self.root_path).analyze(path,progress=lambda done,total:self.analysis_events.put(('progress',done,total)),cancel_event=self.cancel_analysis);self.analysis_events.put(('done',timeline))
            except AnalysisCancelled:self.analysis_events.put(('cancel',))
            except Exception as error:self.analysis_events.put(('error',str(error)))
        threading.Thread(target=run,name='prediction-analysis',daemon=True).start();self.after(80,self._drain_analysis)
    def _drain_analysis(self):
        try:
            while True:
                event=self.analysis_events.get_nowait()
                if event[0]=='progress':self.pred_status.set(f'正在分析视频…… {event[1]} / {event[2]} 帧  {event[1]*100//max(1,event[2])}%')
                elif event[0]=='done':
                    duration=self.video.total_frames/self.video.fps if self.video else 0;self.pred_rows=self.predictions.generate_anchors(self.experiment['id'],event[1],duration);self.cancel_analysis=None;self.analyze_button.state(['!disabled']);self.refresh_prediction();
                    if not self.pred_rows:self.pred_status.set('该视频虽然产生了预测，但没有足够的未来30秒时间用于完整 +10/+20/+30 验证。建议使用更长的视频进行正式预测研究。')
                else:self.cancel_analysis=None;self.analyze_button.state(['!disabled']);self.pred_status.set('预测分析已取消。' if event[0]=='cancel' else '分析错误：'+event[1])
        except queue.Empty:pass
        if self.cancel_analysis:self.after(80,self._drain_analysis)
    def cancel_prediction_analysis(self):
        if self.cancel_analysis:self.cancel_analysis.set()
    def view_prediction_target(self,h):
        if not self.pred_rows:return
        a=self.pred_rows[self.pred_index];target_time,frame=prediction_target(a['anchor_time_seconds'],h,self.video.fps);self._prediction_target=(h,target_time,frame);self._send('read_raw',frame);self.pred_view_label.set(f'当前查看：+{h}秒 Ground Truth  |  目标时间：{target_time:.2f} s  |  帧号：{frame}');self.pred_status.set('请观察原始画面，人工记录该时刻真实人数。')
    def reference_count_gt(self,h):
        if not self.pred_rows:return
        a=self.pred_rows[self.pred_index];value=self.predictions.apply_existing_count_gt(a['id'],h)
        if value is None:messagebox.showinfo('预测 Ground Truth','该时刻没有可引用的人工 Ground Truth。',parent=self)
        else:self.pred_gt[h].set(str(value));self.refresh_prediction()
    def save_prediction(self,next=False):
        if not self.pred_rows:return
        a=self.pred_rows[self.pred_index]
        try:
            for h in (10,20,30):
                value=self.pred_gt[h].get().strip()
                if value:self.predictions.save_prediction_gt(a['id'],h,int(value))
        except (ValueError,TypeError):messagebox.showwarning('输入错误','人工真实人数必须是非负整数。',parent=self);return
        self.refresh_prediction()
        if next:self.show_prediction(self.pred_index+1)

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
        if not path.is_file():self.status.set('原始视频文件不存在；数据库内容仍可查看');self.refresh_prediction();return
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
            if r.operation=='open_video':self.video=r.value;self.show(0);self.refresh_prediction()
            else:self.render(r.value)
        self.after(40,self._drain)
    def show(self,i):
        if not self.tasks or self.busy:return
        self.index=max(0,min(i,len(self.tasks)-1));a=self.tasks[self.index];self.gt.set('' if a['ground_truth_count'] is None else str(a['ground_truth_count']));self.note.set(a['note']);self.point.set(f"第 {self.index+1} / {len(self.tasks)} 个  |  时间：{a['video_time_seconds']:.2f} s  | 帧：{a['frame_index']}");self.result.set('正式研究：请先独立填写人工人数。' if self.experiment['experiment_type']=='formal' and a['ground_truth_count'] is None else (f"系统人数：{a['system_count']}；人工人数：{a['ground_truth_count']}；绝对误差：{a['absolute_error']}" if a['system_count'] is not None else ''));self._send('read_raw',a['frame_index']);self.refresh()
    def _show_frame(self, target, frame_bgr, prediction=False):
        try:
            from PIL import Image,ImageTk
            image=Image.fromarray(frame_bgr[:,:,::-1])
            image.thumbnail(tuple(scaled_value(value,self._zoom_factor) for value in BASE_VIDEO_SIZE))
            photo=ImageTk.PhotoImage(image)
            if prediction:self._prediction_photo=photo
            else:self.photo=photo
            target.configure(image=photo,text='')
        except Exception as error:
            target.configure(text=str(error),image='')

    def on_zoom_changed(self, factor):
        self._zoom_factor=factor
        if self.mode.get() == 'prediction' and self._prediction_frame_bgr is not None:
            self._show_frame(self.pred_image,self._prediction_frame_bgr,prediction=True)
        elif self._count_frame_bgr is not None:
            self._show_frame(self.image,self._count_frame_bgr)
        self.after_idle(lambda:self.canvas.configure(scrollregion=self.canvas.bbox('all')))

    def render(self,p):
        prediction=self.mode.get() == 'prediction' and self._prediction_target is not None
        if prediction:self._prediction_frame_bgr=p.frame_bgr;self._show_frame(self.pred_image,p.frame_bgr,prediction=True)
        else:self._count_frame_bgr=p.frame_bgr;self._show_frame(self.image,p.frame_bgr)
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
        out=self.counts.export_experiment(self.experiment['id'],self.data_root/'validation'/'exports');messagebox.showinfo('导出完成',f"导出完成：\n{out}",parent=self)
    def close(self):
        self.closing=True
        if self.cancel_analysis:self.cancel_analysis.set()
        self.worker.close()
