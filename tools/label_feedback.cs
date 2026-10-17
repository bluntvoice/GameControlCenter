using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;

// Read-only input sampling. No keyboard, mouse or phone input is injected here.
public sealed class LabelFeedbackState {
    readonly Dictionary<string,double> levels = new Dictionary<string,double>();
    readonly Dictionary<string,long> expiry = new Dictionary<string,long>();
    readonly double leftDeadzone, rightDeadzone;
    static readonly string[] keys = {"Key_1","Key_2","Key_3","Key_4","Key_5","Key_6","Key_9","Key_0","Key_Minus","Key_Equal","Key_BracketLeft","Key_BracketRight","Key_Return","Key_Backspace"};
    static readonly ushort[] masks = {4096,8192,16384,32768,256,512,1,2,4,8,64,128,16,32};
    public LabelFeedbackState(double left, double right) { leftDeadzone=left;rightDeadzone=right; }
    public void Pulse(string key,double strength,long now,int duration=120) {
        levels[key]=Math.Max(0,Math.Min(1,strength));expiry[key]=now+duration;
    }
    static double Axis(short x,short y,double deadzone) {
        double radius=Math.Min(1,Math.Sqrt((double)x*x+(double)y*y)/32767.0);
        return radius<=deadzone ? 0 : (radius-deadzone)/(1-deadzone);
    }
    public void Update(bool connected,ushort buttons,byte lt,byte rt,short lx,short ly,short rx,short ry,long now) {
        if(!connected) {levels.Clear();expiry.Clear();return;}
        for(int i=0;i<keys.Length;i++) if((buttons&masks[i])!=0) Pulse(keys[i],1,now);
        if(lt>40) Pulse("Key_7",1,now);
        if(rt>40) Pulse("Key_8",1,now);
        double left=Axis(lx,ly,leftDeadzone),right=Axis(rx,ry,rightDeadzone);
        if(left>0) Pulse("wheel",left,now,70);
        if(right>0) Pulse("camera",right,now,70);
    }
    public Dictionary<string,double> Read(long now) {
        var result=new Dictionary<string,double>();
        foreach(var p in levels) if(expiry[p.Key]>now) result[p.Key]=p.Value;
        return result;
    }
}

public sealed class LabelFeedbackSnapshot {
    public Dictionary<string,double> Levels;
    public int MouseX,MouseY;
    public uint MousePid;
    public bool MouseActive;
}

public sealed class LabelFeedbackSampler : IDisposable {
    [StructLayout(LayoutKind.Sequential)] struct Pad {public ushort buttons;public byte lt,rt;public short lx,ly,rx,ry;}
    [StructLayout(LayoutKind.Sequential)] struct State {public uint packet;public Pad pad;}
    [StructLayout(LayoutKind.Sequential)] struct Point {public int x,y;}
    [DllImport("xinput1_4.dll")] static extern uint XInputGetState(uint index,out State state);
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")] static extern bool GetCursorPos(out Point point);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
    readonly object gate=new object(); readonly LabelFeedbackState state;
    readonly Thread worker; volatile bool stopped;
    int index=-1,mouseX,mouseY;uint mousePid;long mouseUntil;
    public LabelFeedbackSampler(double left,double right) {
        state=new LabelFeedbackState(left,right);
        worker=new Thread(Run);worker.IsBackground=true;worker.Name="Controller label feedback";worker.Start();
    }
    void Run() {
        while(!stopped) {
            State sample=new State(); bool connected=false;
            if(index>=0) connected=XInputGetState((uint)index,out sample)==0;
            if(!connected) {
                index=-1;
                for(uint i=0;i<4;i++) if(XInputGetState(i,out sample)==0) {index=(int)i;connected=true;break;}
            }
            long now=Environment.TickCount64;
            bool mouse=(GetAsyncKeyState(1)&0x8000)!=0;
            bool rightMouse=(GetAsyncKeyState(2)&0x8000)!=0;
            Point point=new Point();uint pid=0;
            if(mouse||rightMouse) {GetCursorPos(out point);GetWindowThreadProcessId(WindowFromPoint(point),out pid);}
            lock(gate) {
                Pad p=sample.pad;state.Update(connected,p.buttons,p.lt,p.rt,p.lx,p.ly,p.rx,p.ry,now);
                if(mouse) state.Pulse("LeftButton",1,now);
                if(rightMouse) state.Pulse("RightButton",1,now);
                if(mouse) {mouseX=point.x;mouseY=point.y;mousePid=pid;mouseUntil=now+120;}
            }
            Thread.Sleep(8);
        }
    }
    public LabelFeedbackSnapshot Read() {
        lock(gate) {return new LabelFeedbackSnapshot {Levels=state.Read(Environment.TickCount64),
            MouseX=mouseX,MouseY=mouseY,MousePid=mousePid,MouseActive=Environment.TickCount64<mouseUntil};}
    }
    public void Dispose() {stopped=true;worker.Join(500);}
}
