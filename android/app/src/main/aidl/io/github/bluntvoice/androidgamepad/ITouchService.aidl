package io.github.bluntvoice.androidgamepad;

interface ITouchService {
    String open(IBinder owner, int targetUid, String foregroundPackage) = 0;
    String frame(in String[] ids, in float[] coordinates) = 1;
    String close() = 2;
    void destroy() = 16777114;
}
