// Decompile selected guest functions from EMAIN.elf with Ghidra headless.
// Usage:
//   analyzeHeadless <proj> GT6 -import work\bin\EMAIN.elf -noanalysis \
//     -scriptPath tools\ghidra_scripts -postScript DecompileAt.java \
//     0x9E191C:0x9E1C0C:value_cmp 0x5F299C:0x5F2D00:adhoc_reader \
//     C:\path\out.c -deleteProject
//
// Each spec is start:end[:name]. Addresses are guest EAs (hex). The script
// disassembles the range, creates a function if needed, and writes decompiled C.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.PrintWriter;

public class DecompileAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: start:end[:name] ... outfile");
            return;
        }
        String outPath = args[args.length - 1];
        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        PrintWriter w = new PrintWriter(new BufferedWriter(new FileWriter(outPath)));
        w.println("// Ghidra decompilation of " + currentProgram.getName());
        for (int i = 0; i < args.length - 1; i++) {
            String[] p = args[i].split(":");
            long start = Long.parseLong(p[0].replace("0x", "").replace("0X", ""), 16);
            long end = Long.parseLong(p[1].replace("0x", "").replace("0X", ""), 16);
            String name = p.length > 2 ? p[2] : String.format("func_%08X", start);
            Address a = toAddr(start);
            Address b = toAddr(end);
            DisassembleCommand cmd = new DisassembleCommand(a, new AddressSet(a, b), true);
            cmd.applyTo(currentProgram, monitor);
            Function f = getFunctionAt(a);
            if (f == null)
                f = createFunction(a, name);
            if (f == null) {
                w.println("/* no function at " + a + " */");
                continue;
            }
            f.setName(name, SourceType.USER_DEFINED);
            DecompileResults r = ifc.decompileFunction(f, 120, monitor);
            w.println("/* ===== " + name + " @ " + a + " .. " + b + " ===== */");
            if (r.decompileCompleted())
                w.println(r.getDecompiledFunction().getC());
            else
                w.println("/* decompile failed: " + r.getErrorMessage() + " */");
        }
        w.close();
        ifc.dispose();
        println("wrote " + outPath);
    }
}
