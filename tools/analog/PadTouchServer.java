import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.util.*;

/** Local companion. Loads the unmodified bundled GameScrcpy classes at runtime. */
public final class PadTouchServer {
    private final Object touch;
    private final Method inject;
    private final Map<Integer,int[]> active = new LinkedHashMap<Integer,int[]>();
    private final int display, width, height;
    private final Object displayManager;
    private final Method getDisplayInfo;
    private long displayCheck;
    private int rotation=-1;

    PadTouchServer(int display, int width, int height) throws Exception {
        this.display=display; this.width=width; this.height=height;
        Class<?> looper=Class.forName("android.os.Looper");
        looper.getMethod("prepare").invoke(null);
        Field main=looper.getDeclaredField("sMainLooper"); main.setAccessible(true);
        main.set(null,looper.getMethod("myLooper").invoke(null));
        Class.forName("com.genymobile.scrcpy.Workarounds").getMethod("apply").invoke(null);
        Class<?> dm=Class.forName("android.hardware.display.DisplayManagerGlobal");
        displayManager=dm.getMethod("getInstance").invoke(null);
        getDisplayInfo=dm.getMethod("getDisplayInfo",int.class);
        checkDisplay();
        Class<?> ft=Class.forName("com.genymobile.scrcpy.control.FastTouch");
        touch=ft.getConstructor().newInstance();
        ft.getMethod("setDisplaySize",int.class,int.class).invoke(touch,width,height);
        ft.getMethod("setTargetDisplayId",int.class).invoke(touch,display);
        inject=ft.getMethod("inject",int.class,int.class,int.class,int.class);
    }
    private void checkDisplay() throws Exception {
        Object info=getDisplayInfo.invoke(displayManager,display);
        if(info==null) throw new IOException("Target display disappeared");
        int w=info.getClass().getField("logicalWidth").getInt(info);
        int h=info.getClass().getField("logicalHeight").getInt(info);
        int r=info.getClass().getField("rotation").getInt(info);
        if(w!=width || h!=height) throw new IOException("Display size changed; restart companion");
        if(rotation!=-1 && r!=rotation) throw new IOException("Display rotated; restart companion");
        rotation=r;
        displayCheck=System.nanoTime();
    }
    private void event(int id,int action,int[] p) throws Exception {
        if(!((Boolean)inject.invoke(touch,id,action,p[0],p[1])).booleanValue())
            throw new IOException("Input injection failed");
    }
    private void release() {
        for(Map.Entry<Integer,int[]> e:new ArrayList<Map.Entry<Integer,int[]>>(active.entrySet())) {
            try { event(e.getKey(),1,e.getValue()); } catch(Exception ex) { System.err.println("Release failed: "+ex); }
        }
        active.clear();
    }
    private void frame(byte[] bytes) throws Exception {
        if(System.nanoTime()-displayCheck>500000000L) checkDisplay();
        DataInputStream in=new DataInputStream(new ByteArrayInputStream(bytes));
        int count=in.readUnsignedByte();
        if(count>10 || bytes.length!=1+count*5) throw new IOException("Invalid snapshot");
        Map<Integer,int[]> next=new LinkedHashMap<Integer,int[]>();
        for(int i=0;i<count;i++) {
            int id=in.readUnsignedByte();
            if(id<1 || id>20 || next.containsKey(id)) throw new IOException("Invalid pointer id");
            next.put(id,new int[]{in.readUnsignedShort(),in.readUnsignedShort()});
        }
        for(Integer id:new ArrayList<Integer>(active.keySet())) {
            if(!next.containsKey(id)) { event(id,1,active.get(id)); active.remove(id); }
        }
        for(Map.Entry<Integer,int[]> e:next.entrySet()) {
            int id=e.getKey(); int[] pos=e.getValue();
            boolean down=!active.containsKey(id);
            // Track before injection so finally can release even if a method throws after delivery.
            active.put(id,pos);
            event(id,down?0:2,pos);
        }
    }
    private void serve(int port,String token) throws Exception {
        // Loopback only. PC connects using an explicitly owned ADB forwarding rule.
        try(ServerSocket listener=new ServerSocket()) {
            listener.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),port));
            listener.setSoTimeout(10000);
            System.out.println("PAD_READY display="+display+" size="+width+"x"+height);
            try(Socket socket=listener.accept()) {
                socket.setTcpNoDelay(true); socket.setSoTimeout(500);
                DataInputStream in=new DataInputStream(socket.getInputStream());
                DataOutputStream out=new DataOutputStream(socket.getOutputStream());
                if(!token.equals(in.readUTF())) throw new IOException("Authentication failed");
                out.writeInt(0x47504332); out.flush();
                socket.setSoTimeout(50);
                // Keep partial headers/bodies across a read timeout. DataInputStream
                // readFully cannot resume a partly consumed header after timeout.
                byte[] header=new byte[2], data=null;
                int headerRead=0, bodyRead=0;
                long lastFrame=System.nanoTime();
                boolean needsNeutral=false;
                while(true) {
                    if(System.nanoTime()-lastFrame>=500000000L && !needsNeutral) {
                        release(); needsNeutral=true;
                        System.out.println("PAD_IDLE released; connection retained");
                    }
                    try {
                        if(headerRead<2) {
                            int n=in.read(header,headerRead,2-headerRead);
                            if(n<0) break;
                            headerRead+=n;
                            if(headerRead<2) continue;
                            int length=((header[0]&255)<<8)|(header[1]&255);
                            if(length==0) break;
                            if(length>51) throw new IOException("Oversized frame");
                            data=new byte[length]; bodyRead=0;
                        }
                        int n=in.read(data,bodyRead,data.length-bodyRead);
                        if(n<0) break;
                        bodyRead+=n;
                        if(bodyRead<data.length) continue;
                        if(System.nanoTime()-lastFrame>=500000000L && !needsNeutral) {
                            release(); needsNeutral=true;
                        }
                        if(needsNeutral && (data[0]&255)!=0) {
                            // Reject a delayed held stick/button instead of replaying it.
                            out.writeByte(255);
                        } else {
                            frame(data);
                            if((data[0]&255)==0) needsNeutral=false;
                            out.writeByte(active.size());
                        }
                        out.flush(); lastFrame=System.nanoTime();headerRead=0;data=null;
                    } catch(SocketTimeoutException timeout) {
                        // The next loop releases input at the watchdog deadline;
                        // framing and the authenticated connection remain intact.
                    }
                }
            } finally { release(); }
        }
    }
    public static void main(String[] args) {
        try {
            if(args.length!=5) throw new IllegalArgumentException("display width height port token");
            PadTouchServer server=new PadTouchServer(Integer.parseInt(args[0]),Integer.parseInt(args[1]),Integer.parseInt(args[2]));
            server.serve(Integer.parseInt(args[3]),args[4]);
            System.out.println("PAD_STOPPED released");
        } catch(Throwable ex) { ex.printStackTrace(); System.exit(1); }
    }
}
