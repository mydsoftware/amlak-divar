# -*- coding: utf-8 -*-
"""مدیریت سرنخ‌های مجاز و رضایت‌محور دیوار — نسخه پایه ویندوز"""
from __future__ import annotations
import sqlite3
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
DB = DATA / "leads.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT '',
 city TEXT NOT NULL DEFAULT '',
 keywords TEXT NOT NULL DEFAULT '',
 message_template TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS leads (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 campaign_id INTEGER,
 ad_url TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL DEFAULT '',
 city TEXT NOT NULL DEFAULT '',
 public_contact TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 consent_status TEXT NOT NULL DEFAULT 'نامشخص',
 stage TEXT NOT NULL DEFAULT 'جدید',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
);
"""

def connect():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("مدیریت سرنخ دیوار | نسخه پایه")
        self.geometry("1180x760")
        self.minsize(980, 650)
        self.option_add("*Font", "Tahoma 10")
        self.campaign_id = None
        self._style()
        self._build()
        self.refresh_campaigns()
        self.refresh_leads()

    def _style(self):
        s=ttk.Style(self)
        try: s.theme_use("clam")
        except tk.TclError: pass
        s.configure("Treeview", rowheight=28, font=("Tahoma",9))
        s.configure("Treeview.Heading", font=("Tahoma",9,"bold"))
        s.configure("TButton", padding=7)
        s.configure("Header.TLabel", font=("Tahoma",17,"bold"), foreground="#164e63")

    def _build(self):
        header=ttk.Frame(self,padding=14); header.pack(fill="x")
        ttk.Label(header,text="سامانه مدیریت سرنخ‌های دیوار",style="Header.TLabel").pack(side="right")
        ttk.Label(header,text="نسخه پایه • ذخیره محلی • خروجی اکسل",foreground="#64748b").pack(side="left")
        self.tabs=ttk.Notebook(self); self.tabs.pack(fill="both",expand=True,padx=12,pady=8)
        self.camp_tab=ttk.Frame(self.tabs,padding=12); self.tabs.add(self.camp_tab,text="کمپین‌ها و جستجو")
        self.lead_tab=ttk.Frame(self.tabs,padding=12); self.tabs.add(self.lead_tab,text="بانک سرنخ‌ها")
        self._build_campaign_tab(); self._build_leads_tab()
        footer=ttk.Label(self,text="یادآوری: پیام تبلیغاتی ناخواسته در چت دیوار ارسال نکنید. پیام‌رسانی فقط در جریان مجاز و با رضایت/درخواست مخاطب انجام شود.",foreground="#9a3412",padding=8)
        footer.pack(fill="x")

    def _build_campaign_tab(self):
        f=self.camp_tab
        form=ttk.LabelFrame(f,text="تعریف کمپین",padding=12); form.pack(fill="x")
        self.c_name=tk.StringVar(); self.c_category=tk.StringVar(); self.c_city=tk.StringVar(value="دزفول"); self.c_keywords=tk.StringVar()
        fields=[("نام کمپین",self.c_name),("حوزه / دسته",self.c_category),("کد شهر در دیوار (مثلاً dezful)",self.c_city),("کلمات کلیدی (با ویرگول)",self.c_keywords)]
        for i,(label,var) in enumerate(fields):
            r,c=divmod(i,2)
            cell=ttk.Frame(form); cell.grid(row=r,column=c,sticky="ew",padx=6,pady=5)
            ttk.Label(cell,text=label).pack(anchor="e")
            ttk.Entry(cell,textvariable=var,justify="right").pack(fill="x")
        form.columnconfigure(0,weight=1); form.columnconfigure(1,weight=1)
        ttk.Label(form,text="متن پیام پیشنهادی (صرفاً برای پاسخ به درخواست/مکالمه مجاز؛ نه تبلیغ سرد):").grid(row=2,column=0,columnspan=2,sticky="e",padx=6,pady=(8,2))
        self.c_message=tk.Text(form,height=3,wrap="word"); self.c_message.grid(row=3,column=0,columnspan=2,sticky="ew",padx=6)
        actions=ttk.Frame(form); actions.grid(row=4,column=0,columnspan=2,sticky="e",pady=8)
        ttk.Button(actions,text="ذخیره کمپین",command=self.save_campaign).pack(side="right",padx=4)
        ttk.Button(actions,text="بازکردن جستجوی دیوار",command=self.open_search).pack(side="right",padx=4)
        ttk.Button(actions,text="پاک‌کردن فرم",command=self.clear_campaign).pack(side="right",padx=4)
        lower=ttk.LabelFrame(f,text="کمپین‌های ذخیره‌شده",padding=8); lower.pack(fill="both",expand=True,pady=12)
        self.campaign_tree=ttk.Treeview(lower,columns=("id","name","category","city","keywords"),show="headings",height=8)
        for col,title,w in [("id","شناسه",60),("name","نام کمپین",220),("category","حوزه",170),("city","شهر",120),("keywords","کلمات کلیدی",400)]:
            self.campaign_tree.heading(col,text=title); self.campaign_tree.column(col,width=w,anchor="e")
        self.campaign_tree.pack(fill="both",expand=True)
        self.campaign_tree.bind("<<TreeviewSelect>>",self.select_campaign)
        ttk.Label(f,text="جستجو در مرورگر به‌صورت هدایت به صفحه دیوار انجام می‌شود؛ ثبت اطلاعات آگهی در این نسخه با ورود دستی و بدون استخراج خودکار اطلاعات شخصی است.",foreground="#475569").pack(anchor="e")

    def _build_leads_tab(self):
        f=self.lead_tab
        form=ttk.LabelFrame(f,text="ثبت سرنخ",padding=12); form.pack(fill="x")
        self.l_url=tk.StringVar(); self.l_title=tk.StringVar(); self.l_category=tk.StringVar(); self.l_city=tk.StringVar(); self.l_contact=tk.StringVar(); self.l_consent=tk.StringVar(value="نامشخص"); self.l_stage=tk.StringVar(value="جدید")
        items=[("لینک آگهی",self.l_url),("عنوان آگهی",self.l_title),("حوزه",self.l_category),("شهر",self.l_city),("راه تماس عمومی/مجاز",self.l_contact)]
        for i,(label,var) in enumerate(items):
            r,c=divmod(i,2); cell=ttk.Frame(form); cell.grid(row=r,column=c,sticky="ew",padx=6,pady=4)
            ttk.Label(cell,text=label).pack(anchor="e"); ttk.Entry(cell,textvariable=var,justify="right").pack(fill="x")
        r=3
        cell=ttk.Frame(form); cell.grid(row=r,column=0,sticky="ew",padx=6,pady=4)
        ttk.Label(cell,text="وضعیت رضایت").pack(anchor="e")
        ttk.Combobox(cell,textvariable=self.l_consent,values=["نامشخص","رضایت ثبت‌شده","درخواست تماس داده","عدم رضایت"],state="readonly").pack(fill="x")
        cell=ttk.Frame(form); cell.grid(row=r,column=1,sticky="ew",padx=6,pady=4)
        ttk.Label(cell,text="مرحله فروش").pack(anchor="e")
        ttk.Combobox(cell,textvariable=self.l_stage,values=["جدید","بررسی‌شده","مشتری علاقه‌مند","مشتری","عدم تمایل","بایگانی"],state="readonly").pack(fill="x")
        form.columnconfigure(0,weight=1); form.columnconfigure(1,weight=1)
        ttk.Label(form,text="یادداشت").grid(row=4,column=0,columnspan=2,sticky="e",padx=6)
        self.l_notes=tk.Text(form,height=2,wrap="word"); self.l_notes.grid(row=5,column=0,columnspan=2,sticky="ew",padx=6)
        btns=ttk.Frame(form); btns.grid(row=6,column=0,columnspan=2,sticky="e",pady=7)
        ttk.Button(btns,text="ذخیره سرنخ",command=self.save_lead).pack(side="right",padx=4)
        ttk.Button(btns,text="بازکردن آگهی انتخاب‌شده",command=self.open_selected).pack(side="right",padx=4)
        ttk.Button(btns,text="خروجی اکسل",command=self.export_excel).pack(side="right",padx=4)
        ttk.Button(btns,text="به‌روزرسانی",command=self.refresh_leads).pack(side="right",padx=4)
        listing=ttk.LabelFrame(f,text="سرنخ‌های ثبت‌شده",padding=8); listing.pack(fill="both",expand=True,pady=10)
        cols=("id","title","category","city","contact","consent","stage","url")
        self.lead_tree=ttk.Treeview(listing,columns=cols,show="headings")
        titles={"id":"شناسه","title":"عنوان آگهی","category":"حوزه","city":"شهر","contact":"راه تماس","consent":"رضایت","stage":"وضعیت","url":"لینک"}
        widths={"id":55,"title":220,"category":100,"city":90,"contact":140,"consent":115,"stage":110,"url":300}
        for col in cols:
            self.lead_tree.heading(col,text=titles[col]); self.lead_tree.column(col,width=widths[col],anchor="e")
        self.lead_tree.pack(fill="both",expand=True)
        self.lead_tree.bind("<<TreeviewSelect>>",self._select_lead)

    def save_campaign(self):
        name=self.c_name.get().strip()
        if not name: messagebox.showwarning("ورودی ناقص","نام کمپین را وارد کنید."); return
        values=(name,self.c_category.get().strip(),self.c_city.get().strip(),self.c_keywords.get().strip(),self.c_message.get("1.0","end").strip())
        with connect() as con:
            if self.campaign_id:
                con.execute("UPDATE campaigns SET name=?,category=?,city=?,keywords=?,message_template=? WHERE id=?",values+(self.campaign_id,))
            else:
                cur=con.execute("INSERT INTO campaigns(name,category,city,keywords,message_template) VALUES(?,?,?,?,?)",values)
                self.campaign_id=cur.lastrowid
        self.refresh_campaigns(); messagebox.showinfo("ذخیره شد","کمپین ذخیره شد.")

    def clear_campaign(self):
        for v in (self.c_name,self.c_category,self.c_keywords): v.set("")
        self.c_city.set("دزفول"); self.c_message.delete("1.0","end"); self.campaign_id=None

    def refresh_campaigns(self):
        for x in self.campaign_tree.get_children(): self.campaign_tree.delete(x)
        with connect() as con:
            for row in con.execute("SELECT id,name,category,city,keywords FROM campaigns ORDER BY id DESC"):
                self.campaign_tree.insert("","end",values=row)

    def select_campaign(self,_event=None):
        selected=self.campaign_tree.selection()
        if not selected:return
        vals=self.campaign_tree.item(selected[0],"values")
        self.campaign_id=int(vals[0])
        with connect() as con:
            row=con.execute("SELECT name,category,city,keywords,message_template FROM campaigns WHERE id=?",(self.campaign_id,)).fetchone()
        self.c_name.set(row[0]); self.c_category.set(row[1]); self.c_city.set(row[2]); self.c_keywords.set(row[3])
        self.c_message.delete("1.0","end"); self.c_message.insert("1.0",row[4])

    def open_search(self):
        city=self.c_city.get().strip() or "iran"
        keywords=self.c_keywords.get().strip() or self.c_category.get().strip()
        city_slug=city.lower().replace(" ","-") if city.isascii() else "iran"\n        url=f"https://divar.ir/s/{quote_plus(city_slug)}"
        if keywords:url += f"?q={quote_plus(keywords)}"
        webbrowser.open(url)

    def save_lead(self):
        url=self.l_url.get().strip()
        if not url.startswith("https://divar.ir/"):
            messagebox.showwarning("لینک نامعتبر","لینک معتبر آگهی دیوار را وارد کنید."); return
        if not self.l_title.get().strip():
            messagebox.showwarning("ورودی ناقص","عنوان آگهی را وارد کنید."); return
        try:
            with connect() as con:
                con.execute("""INSERT INTO leads(campaign_id,ad_url,title,category,city,public_contact,notes,consent_status,stage)
                VALUES(?,?,?,?,?,?,?,?,?)""",(self.campaign_id,url,self.l_title.get().strip(),self.l_category.get().strip(),self.l_city.get().strip(),self.l_contact.get().strip(),self.l_notes.get("1.0","end").strip(),self.l_consent.get(),self.l_stage.get()))
        except sqlite3.IntegrityError:
            messagebox.showwarning("تکراری","این لینک قبلاً ثبت شده است."); return
        self.refresh_leads(); messagebox.showinfo("ذخیره شد","سرنخ ذخیره شد.")

    def refresh_leads(self):
        for x in self.lead_tree.get_children(): self.lead_tree.delete(x)
        with connect() as con:
            rows=con.execute("SELECT id,title,category,city,public_contact,consent_status,stage,ad_url FROM leads ORDER BY id DESC").fetchall()
        for row in rows:self.lead_tree.insert("","end",values=row)

    def _select_lead(self,_event=None):
        sel=self.lead_tree.selection()
        if sel:self.selected_url=self.lead_tree.item(sel[0],"values")[-1]
    def open_selected(self):
        sel=self.lead_tree.selection()
        if not sel: messagebox.showinfo("انتخاب","ابتدا یک سرنخ انتخاب کنید."); return
        webbrowser.open(self.lead_tree.item(sel[0],"values")[-1])

    def export_excel(self):
        path=filedialog.asksaveasfilename(defaultextension=".xlsx",filetypes=[("Excel","*.xlsx")],initialfile="divar_leads.xlsx")
        if not path:return
        with connect() as con:
            rows=con.execute("""SELECT id,title,category,city,public_contact,notes,consent_status,stage,ad_url,created_at FROM leads ORDER BY id DESC""").fetchall()
        headers=["شناسه","عنوان آگهی","حوزه","شهر","راه تماس عمومی/مجاز","یادداشت","وضعیت رضایت","مرحله فروش","لینک آگهی","تاریخ ثبت"]
        wb=Workbook(); ws=wb.active; ws.title="سرنخ‌ها"; ws.sheet_view.rightToLeft=True
        ws.append(headers)
        for row in rows: ws.append(list(row))
        for cell in ws[1]:
            cell.font=Font(name="Tahoma",bold=True,color="FFFFFF")
            cell.fill=PatternFill("solid",fgColor="164E63")
            cell.alignment=Alignment(horizontal="center",vertical="center")
        for row in ws.iter_rows(min_row=2):
            for cell in row: cell.alignment=Alignment(horizontal="right",vertical="center")
            url=row[8]
            if url.value:
                url.hyperlink=url.value; url.style="Hyperlink"
        for i,w in enumerate([9,34,18,16,24,40,18,18,50,22],1): ws.column_dimensions[get_column_letter(i)].width=w
        ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
        wb.save(path); messagebox.showinfo("خروجی آماده شد",f"فایل اکسل ذخیره شد:\n{path}")

if __name__=="__main__":
    App().mainloop()
