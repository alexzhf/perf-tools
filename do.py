#!/usr/bin/env python
# Misc utilities for CPU performance analysis on Linux
# Author: Ahmad Yasin
# edited: April 2022
# TODO list:
#   report PEBS-based stats for DSB-miss types (loop-seq, loop-jump_to_mid)
#   MSR 0x6d for servers (LLC prefetch)
#   move profile code to a seperate module, arg for output dir
#   toplevl 3-levels default Icelake onwards
#   quiet mode
#   convert verbose to a bitmask
#   add test command to gate commits to this file
#   replace rp() centrally inside exe()
#   support disable nmi_watchdog in CentOS
#   check sudo permissions
from __future__ import print_function
__author__ = 'ayasin'
__version__= 1.1

import argparse, os.path, sys
import common as C
import pmu
from datetime import datetime
from platform import python_version

RUN_DEF = './run.sh'
TOPLEV_DEF='--metric-group +Summary' #FIXME: argparse should tell whether user specified an options
Find_perf = 'sudo find / -name perf -executable -type f'
cpu = 'cpu_core' if 'hybrid' in pmu.name() else 'cpu'
do = {'run':        RUN_DEF,
  'asm-dump':       30,
  'cmds_file':      None,
  'compiler':       'gcc -O2', # ~/tools/llvm-6.0.0/bin/clang',
  'core':           1,
  'cpuid':          1,
  'dmidecode':      0,
  'extra-metrics':  "+Mispredictions,+IpTB,+BpTkBranch,+IpCall,+IpLoad,+ILP,+UPI",
  'forgive':        0,
  'gen-kernel':     1,
  'loops':          3,
  'lbr-stats':      '- 0 10 0 ANY_DSB_MISS',
  'lbr-stats-tk':   '- 0 20 1',
  'metrics':        "+L2MPKI,+ILP,+IpTB,+IpMispredict", #,+UPI once ICL mux fixed
  'msr':            0,
  'msrs':           ('0x48', '0x8b', '0x1a4'),
  'nodes':          "+CoreIPC,+Instructions,+CORE_CLKS,+CPU_Utilization,+Time,+MUX",
  'numactl':        1,
  'objdump':        './binutils-gdb/binutils/objdump',
  'package-mgr':    C.os_installer(),
  'packages':       ('cpuid', 'dmidecode', 'msr', 'numactl'),
  'perf-lbr':       '-j any,save_type -e %s -c 700001' % pmu.lbr_event(),
  'perf-pebs':      '-b -e %s/event=0xc6,umask=0x1,frontend=0x1,name=FRONTEND_RETIRED.ANY_DSB_MISS/uppp -c 1000003'%cpu,
  'perf-record':    '', # '-e BR_INST_RETIRED.NEAR_CALL:pp ',
  'perf-stat':      '', # '--topdown' if pmu.perfmetrics() else '',
  'perf-stat-def':  'cpu-clock,context-switches,cpu-migrations,page-faults,instructions,cycles,ref-cycles,branches,branch-misses', # ,cycles:G
  'perf-stat-ipc':  '-- perf stat -e instructions,cycles',
  'pin':            'taskset 0x4',
  'pmu':            pmu.name(),
  'python':         sys.executable,
  'profile':        1,
  'repeat':         3,
  'sample':         2,
  'super':          0,
  'tee':            1,
  'toplev':         TOPLEV_DEF,
  'toplev-levels':  2,
  'toplev-full':    '-vl6',
  'xed':            1,
}
args = argparse.Namespace()

def exe(x, msg=None, redir_out='2>&1', verbose=False, run=True, timeit=False, background=False):
  X=x.split()
  if redir_out: redir_out=' %s'%redir_out
  if not do['tee'] and redir_out: x = x.split('|')[0]
  if 'tee >(' in x: x = 'bash -c "%s"'%x.replace('"', '\\"')
  x = x.replace('  ', ' ')
  if timeit: x = 'time -f "\\t%%E time-real:%s" %s 2>&1' % ('-'.join(X[:2]), x)
  if len(vars(args)):
    run = not args.print_only
    if not do['profile']:
      if 'perf stat' in x or 'perf record' in x or 'toplev.py' in x:
        x = '# ' + x
        run = False
    if background: x = x + ' &'
    do['cmds_file'].write(x + '\n')
    do['cmds_file'].flush()
    verbose = args.verbose > 0
  return C.exe_cmd(x, msg, redir_out, verbose, run, background)
def exe_to_null(x): return exe(x + ' > /dev/null', redir_out=None)
def exe_v0(x='true', msg=None): return C.exe_cmd(x, msg) # don't append to cmds_file
def prn_line(f): exe_v0('echo >> %s' % f)

def print_cmd(x, show=True):
  if show: C.printc(x)
  if len(vars(args))>0: do['cmds_file'].write('# ' + x + '\n')

def grep(x, f=''): return "(egrep '%s' %s || true)" % (x, f) # grep with 0 exit status

def rp(x): return os.path.join(os.path.dirname(__file__), x)

def uniq_name():
  return C.command_basename(args.app_name, iterations=(args.app_iterations if args.gen_args else None))

def tools_install(installer='sudo %s install '%do['package-mgr'], packages=[]):
  pkg_name = {'msr': 'msr-tools'}
  if args.install_perf:
    if args.install_perf == 'install':
      if do['package-mgr'] == 'dnf': exe('sudo yum install perf', 'installing perf')
      else: packages += ['linux-tools-generic && ' + Find_perf]
    elif args.install_perf == 'build':
      b='./build-perf.sh'
      if 'apt-get' in C.file2str(b): exe('sed -i s/apt\-get/%s/ %s'%(do['package-mgr'],b))
      exe('%s | tee %s.log'%(b, b.replace('.sh','')), 'building perf anew')
    elif args.install_perf == 'patch':
      exe_v0(msg='setting default perf')
      a_perf = C.exe_output(Find_perf + ' | grep -v /usr/bin/perf | head -1', '')
      exe('ln -f -s %s /usr/bin/perf'%a_perf)
    else: C.error('Unsupported --perf-install option: '+args.install_perf)
  for x in do['packages']:
    if do[x]: packages += [pkg_name[x] if x in pkg_name else x]
  for x in packages:
    exe(installer + x, 'installing ' + x.split(' ')[0])
  if do['xed']:
    if os.path.isfile('/usr/local/bin/xed'): exe_v0(msg='xed is already installed')
    else: exe('./build-xed.sh', 'installing xed')
  if do['msr']: exe('sudo modprobe msr', 'enabling MSRs')

def tools_update(kernels=[], level=3):
  ks = [''] + C.exe2list("git status | grep 'modified.*kernels' | cut -d/ -f2") + kernels
  exe('git checkout HEAD run.sh' + ' kernels/'.join(ks))
  if level > 0: exe('git pull')
  if level > 1: exe('git submodule update --remote')
  if level > 2:
    exe(args.pmu_tools + "/event_download.py ")
    if do['super']:
      if level > 3: exe('mv ~/.cache/pmu-events /tmp')
      exe(args.pmu_tools + "/event_download.py -a") # requires sudo; download all CPUs

def set_sysfile(p, v): exe_to_null('echo %s | sudo tee %s'%(v, p))
def prn_sysfile(p, out=None): exe_v0('printf "%s : %s \n" %s' %
  (p, C.file2str(p), (' >> '+out if out else '')))
def setup_perf(actions=('set', 'log'), out=None):
  def set_it(p, v): set_sysfile(p, str(v))
  TIME_MAX = '/proc/sys/kernel/perf_cpu_time_max_percent'
  perf_params = [
    ('/proc/sys/kernel/perf_event_paranoid', -1, ),
    ('/proc/sys/kernel/perf_event_mlock_kb', 60000, ),
    ('/proc/sys/kernel/perf_event_max_sample_rate', int(1e9), 'root'),
    ('/sys/devices/%s/perf_event_mux_interval_ms'%cpu, 100, ),
    ('/proc/sys/kernel/kptr_restrict', 0, ),
    ('/proc/sys/kernel/nmi_watchdog', 0, ),
    ('/proc/sys/kernel/soft_watchdog', 0, ),
  ]
  if 'set' in actions: exe_v0(msg='setting up perf')
  superv = 'sup' in actions or do['super']
  if superv:
    set_it(TIME_MAX, 25)
    perf_params += [('/sys/devices/cpu/rdpmc', 1, ),
      ('/sys/bus/event_source/devices/cpu/rdpmc', 2, )]
  perf_params += [(TIME_MAX, 0, 'root')] # has to be last
  for x in perf_params: 
    if (len(x) == 2) or superv:
      param, value = x[0], x[1]
      if 'set' in actions: set_it(param, value)
      if 'log' in actions: prn_sysfile(param, out)

def smt(x='off'):
  set_sysfile('/sys/devices/system/cpu/smt/control', x)
  if do['super']: exe(args.pmu_tools + '/cputop "thread == 1" %sline | sudo sh'%x)
def atom(x='offline'):
  exe(args.pmu_tools + "/cputop 'type == \"atom\"' %s"%x)
  exe("for x in {16..23}; do echo %d | sudo tee /sys/devices/system/cpu/cpu$x/online; done" %
    (0 if x == 'offline' else 1))
def fix_frequency(x='on', base_freq=C.file2str('/sys/devices/system/cpu/cpu0/cpufreq/base_frequency')):
  if x == 'on':
    for f in C.glob('/sys/devices/system/cpu/cpu*/cpufreq/scaling_m*_freq'):
      set_sysfile(f, base_freq)
  else:
    for m in ('max', 'min'):
      freq=C.file2str('/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_%s_freq'%m)
      for f in C.glob('/sys/devices/system/cpu/cpu*/cpufreq/scaling_%s_freq'%m):
        set_sysfile(f, freq)

def log_setup(out='setup-system.log', c='setup-cpuid.log', d='setup-dmesg.log'):
  def new_line(): return prn_line(out)
  def read_msr(m): return C.exe_one_line('sudo %s/msr.py %s'%(args.pmu_tools, m))
  C.printc(do['pmu']) #OS
  exe('uname -a > ' + out, 'logging setup')
  exe("cat /etc/os-release | egrep -v 'URL|ID_LIKE|CODENAME' >> " + out)
  for f in ('/sys/kernel/mm/transparent_hugepage/enabled', '/proc/sys/vm/nr_hugepages', '/proc/sys/vm/nr_overcommit_hugepages'):
    prn_sysfile(f, out)
  new_line()          #CPU
  exe("lscpu | tee setup-lscpu.log | egrep 'family|Model|Step|(Socket|Core|Thread)\(' >> " + out)
  if do['msr']:
    for m in do['msrs']: exe('echo "MSR %5s:\t%16s" >> '%(m, read_msr(m)) + out)
  if do['cpuid']: exe("cpuid -1 > %s && cpuid -1r | tee -a %s | grep ' 0x00000001' >> %s"%(c, c, out))
  exe("dmesg -T | tee %s | %s >> %s && %s | tail -1 >> %s" % (d, grep('Performance E|micro'), out, grep('BIOS ', d), out))
  new_line()          #PMU
  exe('echo "PMU: %s" >> %s'%(do['pmu'], out))
  exe('%s --version >> '%args.perf + out)
  setup_perf('log', out)
  exe('echo "python version: %s" >> %s'%(python_version(), out))
  new_line()          #Memory
  if do['numactl']: exe('numactl -H >> ' + out)
  new_line()          #Devices, etc
  exe("lsmod | tee setup-lsmod.log | egrep 'Module|kvm' >> " + out)
  exe("ulimit -a > setup-ulimit.log")
  if do['dmidecode']: exe('sudo dmidecode > setup-memory.log')

def perf_format(es, result=''):
  for e in es.split(','):
    if e.startswith('r') and ':' in e:
      e = e.split(':')
      if len(e[0])==5:   e='%s/event=0x%s,umask=0x%s,name=%s/'%(cpu, e[0][3:5], e[0][1:3], e[1])
      elif len(e[0])==7: e='%s/event=0x%s,umask=0x%s,cmask=0x%s,name=%s/'%(cpu, e[0][5:7], e[0][3:5], e[0][1:3], e[1])
      else: C.error("profile:perf-stat: invalid syntax in '%s'"%':'.join(e))
    result += (e if result=='' else ','+e)
  return result

def profile(log=False, out='run'):
  out = uniq_name()
  perf = args.perf
  def en(n): return args.profile_mask & 2**n
  def a_events():
    def power(rapl=['pkg', 'cores', 'ram'], px='/,power/energy-'): return px[(px.find(',')+1):] + px.join(rapl) + ('/' if '/' in px else '')
    return power() if args.power and not pmu.v5p() else ''
  def perf_stat(flags='', events='', grep='| egrep "seconds [st]|CPUs|GHz|insn|topdown"'):
    def append(x, y): return x if y == '' else ','+x
    perf_args = ' '.join((flags, do['perf-stat']))
    if pmu.perfmetrics() and do['core']:
      prefix = ',topdown-'
      events += prefix.join([append('{slots', events),'retiring','bad-spec','fe-bound','be-bound'])
      events += (prefix.join(['', 'heavy-ops','br-mispredict','fetch-lat','mem-bound}']) if pmu.goldencove() else '}')
      if pmu.alderlake(): events = events.replace(prefix, '/,cpu_core/topdown-').replace('}', '/}').replace('{slots/', '{slots')
    if args.events:
      events += append(perf_format(args.events), events)
      grep = '' #keep output unfiltered with user-defined events
    if events != '': perf_args += ' -e "%s,%s"'%(do['perf-stat-def'], events)
    return '%s stat %s -- %s | tee %s.perf_stat%s.log %s'%(perf, perf_args, r, out, flags.strip(), grep)
  def perf_script(x, msg):
    return exe(' '.join((perf, 'script', x)), msg, redir_out=None, timeit=(args.verbose > 1))
  def record_name(flags):
    return '%s%s'%(out, C.chop(flags, (' :/,=', 'cpu_core', 'cpu')))
  
  perf_stat_log = "%s.perf_stat.log"%out
  perf_report = ' '.join((perf, 'report', '--objdump %s'%do['objdump'] if os.path.isfile(do['objdump']) else ''))
  sort2u = 'sort | uniq -c | sort -n'
  sort2up = sort2u + ' | %s'%rp('ptage')
  r = do['run']
  if en(0) or log: log_setup()
  
  if en(1): exe(perf_stat(flags='-r%d' % do['repeat']), 'per-app counting %d runs' % do['repeat'])
  
  if en(2): exe(perf_stat('-a', a_events(), grep='| egrep "seconds|insn|topdown|pkg"'), 'system-wide counting')
  
  if en(3) and do['sample']:
    base = out+'.perf'
    if do['perf-record'] and len(do['perf-record']):
      do['perf-record'] += ' '
      base += C.chop(do['perf-record'], ' :/,=')
    data = '%s.perf.data'%record_name(do['perf-record'])
    exe(perf + ' record -c 1000003 -g -o %s '%data+do['perf-record']+r, 'sampling %sw/ stacks'%do['perf-record'])
    print_cmd("Try '%s -i %s' to browse time-consuming sources"%(perf_report, data))
    #TODO:speed: parallelize next 3 exe() invocations & resume once all are done
    exe(perf_report + " --stdio -F sample,overhead,comm,dso,sym -n --no-call-graph -i %s " \
      " | tee %s-funcs.log | grep -A7 Overhead | egrep -v '^# \.|^\s+$|^$' | head | sed 's/[ \\t]*$//'" %
      (data, base), '@report functions')
    exe(perf_report + " --stdio --hierarchy --header -i %s | grep -v ' 0\.0.%%' | tee "%data+
      base+"-modules.log | grep -A22 Overhead", '@report modules')
    exe(perf + " annotate --stdio -n -l -i %s | c++filt | tee %s-code.log " \
      "| egrep -v -E '^(\-|\s+([A-Za-z:]|[0-9] :))' > %s-code_nz.log" %
      (data, base, base), '@annotate code', redir_out='2>/dev/null')
    hottest = C.exe_one_line("sort -n %s-code.log | tail -1" % base, 0)
    exe("egrep -w -5 '%s :' %s-code.log" % (hottest, base), '@hottest block')
    if do['xed']: perf_script("-i %s -F insn --xed | %s " \
      "| tee %s-hot-insts.log | tail"%(data, sort2up, base), '@time-consuming instructions')
  
  toplev = '' if perf == 'perf' else 'PERF=%s '%perf
  toplev+= (args.pmu_tools + '/toplev.py --no-desc')
  if pmu.alderlake() and do['core']: toplev+= ' --cputype=core'
  grep_bk= "egrep '<==|MUX|Info.Bott' | sort"
  grep_NZ= "egrep -iv '^((FE|BE|BAD|RET).*[ \-][10]\.. |Info.* 0\.0[01]? |RUN|Add)|not (found|supported)|##placeholder##' "
  grep_nz= grep_NZ
  if args.verbose < 2: grep_nz = grep_nz.replace('##placeholder##', ' < [\[\+]|<$')
  def toplev_V(v, tag='', nodes=do['nodes'], tlargs=args.toplev_args):
    o = '%s.toplev%s.log'%(out, v.split()[0]+tag)
    return "%s %s --nodes '%s' -V %s %s -- %s"%(toplev, v, nodes,
              o.replace('.log', '-perf.csv'), tlargs, r), o
  
  cmd, log = toplev_V(do['toplev-full'])
  if en(4): exe(cmd + ' | tee %s | %s'%(log, grep_bk), 'topdown full')
  
  cmd, log = toplev_V('-vl%d'%do['toplev-levels'], tlargs=args.toplev_args+' -r%d' % do['repeat'])
  if en(5): exe(cmd + ' | tee %s | %s' % (log, grep_nz),
              'topdown %d-levels %d runs' % (do['toplev-levels'], do['repeat']))
  
  if en(6):
    cmd, log = toplev_V('--drilldown --show-sample -l1', nodes='+IPC,+Heavy_Operations,+Time',
      tlargs='' if args.toplev_args == TOPLEV_DEF else args.toplev_args)
    exe(cmd + ' | tee %s | egrep -v "^(Run toplev|Add|Using|Sampling|perf record)" '%log, 'topdown auto-drilldown')
    if do['sample'] > 3:
      cmd = C.exe_output("grep 'perf record' %s | tail -1"%log)
      exe(cmd, '@sampling on bottleneck')
      perf_data = cmd.split('-o ')[1].split(' ')[0]
      print_cmd("Try '%s -i %s' to browse sources for critical bottlenecks"%(perf_report, perf_data))
      for c in ('report', 'annotate'):
        exe("%s %s --stdio -i %s > %s "%(perf, c, perf_data, log.replace('toplev--drilldown', 'locate-'+c)), '@'+c)

  if en(7) and args.no_multiplex:
    cmd, log = toplev_V(do['toplev-full']+' --no-multiplex', '-nomux', do['nodes'] + ',' + do['extra-metrics'])
    exe(cmd + " | tee %s | %s"%(log, grep_nz)
      #'| grep ' + ('RUN ' if args.verbose > 1 else 'Using ') + out +# toplev misses stdout.flush() as of now :(
      , 'topdown full no multiplexing')
    print_cmd("cat %s | %s"%(log, grep_NZ), False)
  
  data, comm = None, None
  def perf_record(tag, comm):
    assert '-b' in do['perf-%s'%tag] or '-j any' in do['perf-%s'%tag] or do['forgive'], 'No unfiltered LBRs! tag=%s'%tag
    perf_data = '%s.perf.data'%record_name(do['perf-%s'%tag])
    if do['profile'] > 0: exe(perf + ' record %s -o %s %s -- %s'%(
      do['perf-%s'%tag], perf_data, do['perf-stat-ipc'], r), 'sampling w/ '+tag.upper())
    print_cmd("Try '%s -i %s --branch-history --samples 9' to browse streams"%(perf_report, perf_data))
    if not comm:
      # might be doable to optimize out this 'perf script' with 'perf buildid-list' e.g.
      comm = C.exe_one_line(perf + " script -i %s -F comm | %s | tail -1"%(perf_data, sort2u), 1)
    return perf_data, comm
  
  if en(8) and do['sample'] > 1:
    assert pmu.lbr_event()[:-1] in do['perf-lbr'], 'Incorrect event for LBR in: '+do['perf-lbr']
    data, comm = perf_record('lbr', comm)
    info = '%s.info.log'%data
    exe(perf +" report -i %s | grep -A11 'Branch Statistics:' | tee %s"%(data, info), "@stats")
    if os.path.isfile(perf_stat_log):
      exe("egrep '  branches|instructions' %s >> %s"%(perf_stat_log, info))
    if do['xed']:
      ips = '%s.ips.log'%data
      hits = '%s.hitcounts.log'%data
      exe_v0('printf "\n# LBR-based Statistics:\n#\n">> %s'%info)
      print_cmd(perf + " script -i %s -F +brstackinsn --xed -c %s "
        "| %s %s" % (data, comm, './lbr_stats', do['lbr-stats-tk']))
      perf_script("-i %s -F +brstackinsn --xed -c %s "
        "| tee >(LBR_LOOPS_LOG=%s.loops.log %s %s >> %s) | egrep '^\s[0f7]' | sed 's/#.*//;s/^\s*//;s/\s*$//' "
        "| tee >(sort|uniq -c|sort -k2 | tee %s | cut -f-2 | sort -nu | %s > %s) | cut -f4- "
        "| tee >(cut -d' ' -f1 | %s > %s.perf-imix-no.log) | %s | tee %s.perf-imix.log | tail" %
        (data, comm, data, rp('lbr_stats'), do['lbr-stats-tk'], info, hits, rp('ptage'), ips,
        sort2up, out, sort2up, out), "@instruction-mix for '%s'"%comm)
      exe("tail %s.perf-imix-no.log"%out, "@i-mix no operands for '%s'"%comm)
      exe("tail -4 "+ips, "@top-3 hitcounts of basic-blocks to examine in "+hits)
      exe("%s && tail %s" % (grep('code footprint', info), info), "@hottest loops & more stats in " + info)
      if do['loops']:
        prn_line(info)
        cmd, top = '', do['loops']
        while top > 1:
          cmd += ' | tee >(%s %s >> %s) ' % (rp('loop_stats'),
            C.exe_one_line('tail -%d %s.loops.log | head -1' % (top, data), 2)[:-1], info)
          top -= 1
        cmd += ' | %s %s >> %s' % (rp('loop_stats'), C.exe_one_line('tail -1 %s.loops.log' % data, 2)[:-1], info)
        perf_script("-i %s -F +brstackinsn --xed -c %s %s" % (data, comm, cmd), "@stats for top %d loops" % do['loops'])
  
  if en(9) and do['sample'] > 2:
    data, comm = perf_record('pebs', comm)
    exe(perf + " report -i %s --stdio -F overhead,comm,dso | tee %s.modules.log | grep -A12 Overhead" %
      (data, data), "@ top-10 modules")
    perf_script("-i %s -F ip | %s | tee %s.ips.log | tail -11"%(data, sort2up, data), "@ top-10 IPs")
    is_dsb = 0
    if pmu.dsb_msb() and 'DSB_MISS' in do['perf-pebs']:
      if pmu.cpu('smt-on'): C.warn('Disable SMT for DSB robust analysis')
      else:
        is_dsb = 1
        perf_script("-i %s -F ip | %s %d 6 | %s | tee %s.dsb-sets.log | tail -11" %
                    (data, rp('addrbits'), pmu.dsb_msb(), sort2up, data), "@ DSB-miss sets")
    top = 0
    if not is_dsb: pass
    elif top == 1:
      top_ip = C.exe_one_line("tail -2 %s.ips.log | head -1"%data, 2)
      perf_script("-i %s -F +brstackinsn --xed "
        "| tee >(%s %s | tee -a %s.ips.log) " # asserts in skip_sample() only if piped!!
        "| %s %s | tee -a %s.ips.log"%(data, rp('lbr_stats'), top_ip, data,
            rp('lbr_stats'), do['lbr-stats'], data), "@ stats on PEBS event")
    else:
      perf_script("-i %s -F +brstackinsn --xed "
        "| %s %s | tee -a %s.ips.log"%(data, rp('lbr_stats'), do['lbr-stats'], data), "@ stats on PEBS event")
    if top > 1:
      while top > 0:
        top_ip = C.exe_one_line("egrep '^[0-9]' %s.ips.log | tail -%d | head -1"%(data, top+1), 2)
        perf_script("-i %s -F +brstackinsn --xed "
          "| %s %s | tee -a %s.ips.log"%(data, rp('lbr_stats'), top_ip, data), "@ stats on PEBS ip=%s"%top_ip)
        top -= 1

def do_logs(cmd, ext=[], tag=''):
  log_files = ['', '.cmd', 'csv', 'log', 'txt'] + ext
  res = '%sresults.tar.gz'%tag if cmd == 'tar' else None
  if cmd == 'tar': exe('tar -czvf %s run.sh '%res + ' *.'.join(log_files) + ' .*.cmd')
  if cmd == 'clean': exe('rm -rf ' + ' *.'.join(log_files + ['pyc']) + ' *perf.data* __pycache__ results.tar.gz ')
  return res

def build_kernel(dir='./kernels/'):
  def fixup(x): return x.replace('./', dir)
  app = args.app_name
  if do['gen-kernel']:
    exe(fixup('%s ./gen-kernel.py %s > ./%s.c'%(do['python'], args.gen_args, app)), 'building kernel: ' + app, redir_out=None)
    if args.verbose > 1: exe(fixup('grep instructions ./%s.c'%app))
  exe(fixup('%s -g -o ./%s ./%s.c'%(do['compiler'], app, app)), None if do['gen-kernel'] else 'compiling')
  do['run'] = fixup('%s ./%s %d'%(do['pin'], app, int(float(args.app_iterations))))
  if args.verbose > 2: exe(fixup("objdump -dw ./%s | grep -A%d pause | egrep '[ 0-9a-f]+:'"%(app, do['asm-dump'])), '@kernel ASM')

def parse_args():
  ap = argparse.ArgumentParser(usage='do.py command [command ..] [options]', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  ap.add_argument('command', nargs='+', help='setup-perf log profile tar, all (for these 4) '\
                  '\nsupported options: ' + C.commands_list())
  ap.add_argument('--perf', default='perf', help='use a custom perf tool')
  ap.add_argument('--pmu-tools', default='%s ./pmu-tools'%do['python'], help='use a custom pmu-tools')
  ap.add_argument('--toplev-args', default=do['toplev'], help='arguments to pass-through to toplev')
  ap.add_argument('--install-perf', nargs='?', default=None, const='install', help='perf tool installation options: [install]|patch|build')
  ap.add_argument('--print-only', action='store_const', const=True, default=False, help='print the commands without running them')
  ap.add_argument('-m', '--metrics', default=do['metrics'], help='user metrics to pass to toplev\'s --nodes')
  ap.add_argument('-e', '--events', help='user events to pass to perf-stat\'s -e')
  ap.add_argument('--power', action='store_const', const=True, default=False, help='collect power metrics/events as well')
  ap.add_argument('-a', '--app-name', default=None, help='name of user-application/kernel/command to profile')
  ap.add_argument('-s', '--sys-wide', type=int, default=0, help='profile system-wide for x seconds. disabled by default')
  ap.add_argument('-g', '--gen-args', help='args to gen-kernel.py')
  ap.add_argument('-ki', '--app-iterations', default='1e9', help='num-iterations of kernel')
  ap.add_argument('-pm', '--profile-mask', type=lambda x: int(x,16), default='17F', help='mask to control stages in the profile command')
  ap.add_argument('-N', '--no-multiplex', action='store_const', const=False, default=True,
    help='skip no-multiplexing reruns')
  ap.add_argument('-v', '--verbose', type=int, default=0, help='verbose level; 0:none, 1:commands, ' \
    '2:+verbose-on metrics|build, 3:+toplev --perf|ASM on kernel build, 4:+args parsing, 5:+event-groups(ALL)')
  ap.add_argument('--tune', nargs='+', help=argparse.SUPPRESS, action='append') # override global variables with python expression
  x = ap.parse_args()
  return x

def main():
  global args
  args = parse_args()
  #args sanity checks
  if (args.gen_args or 'build' in args.command) and not args.app_name:
    C.error('must specify --app-name with any of: --gen-args, build')
  assert not (args.print_only and (args.profile_mask & 0x300)), 'No print-only + lbr/pebs profile-steps'
  assert args.sys_wide >= 0, 'negative duration provided!'
  if args.verbose > 4: args.toplev_args += ' -g'
  if args.verbose > 2: args.toplev_args += ' --perf'
  if args.verbose > 1: args.toplev_args += ' -v'
  if args.app_name: do['run'] = args.app_name
  if args.print_only and args.verbose == 0: args.verbose = 1
  do['nodes'] += ("," + args.metrics)
  if args.tune:
    for tlists in args.tune:
      for t in tlists:
        if t.startswith(':'):
          l = t.split(':')
          t = "do['%s']=%s"%(l[1], l[2] if len(l)==3 else ':'.join(l[2:]))
        if args.verbose > 3: print(t)
        exec(t)
  if args.sys_wide:
    C.info('system-wide profiling')
    do['run'] = 'sleep %d'%args.sys_wide
    for x in ('stat', 'record', 'lbr', 'pebs', 'stat-ipc'): do['perf-'+x] += ' -a'
    args.toplev_args += ' -a'
    args.profile_mask &= 0xFFB # disable system-wide profile-step
  do_cmd = '%s # version %.3f' % (C.argv2str(), __version__)
  C.log_stdout = '%s-out.txt' % ('run-default' if do['run'] == RUN_DEF else uniq_name())
  C.printc('\n\n%s\n%s' % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), do_cmd), log_only=True)
  cmds_file = '.%s.cmd' % uniq_name()
  if os.path.isfile(cmds_file):
    exe_v0('mv %s %s-%d.cmd' % (cmds_file, cmds_file.replace('.cmd', ''), os.getpid()))
  do['cmds_file'] = open(cmds_file, 'w')
  do['cmds_file'].write('# %s\n' % do_cmd)
  if args.verbose > 3: C.printc(str(args))
  
  for c in args.command:
    if   c == 'forgive-me':   pass
    elif c == 'setup-all':
      tools_install()
      setup_perf('set')
    elif c == 'build-perf':   exe('./do.py setup-all --install-perf build -v%d --tune %s'%(args.verbose,
                                  ' '.join([':%s:0'%x for x in (do['packages']+('xed', 'tee'))])))
    elif c == 'setup-perf':   setup_perf()
    elif c == 'find-perf':    exe(Find_perf)
    elif c == 'tools-update': tools_update()
    elif c.startswith('tools-update:'): tools_update(level=int(c.split(':')[1]))
    # TODO: generalize disable/enable features that follow
    elif c == 'disable-smt':  smt()
    elif c == 'enable-smt':   smt('on')
    elif c == 'disable-atom': atom()
    elif c == 'enable-atom':  atom('online')
    elif c == 'disable-hugepages': exe('echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled')
    elif c == 'enable-hugepages':  exe('echo always | sudo tee /sys/kernel/mm/transparent_hugepage/enabled')
    elif c == 'disable-prefetches': exe('sudo wrmsr -a 0x1a4 0xf && sudo rdmsr 0x1a4')
    elif c == 'enable-prefetches':  exe('sudo wrmsr -a 0x1a4 0 && sudo rdmsr 0x1a4')
    elif c == 'enable-fix-freq':    fix_frequency()
    elif c == 'disable-fix-freq':   fix_frequency('undo')
    elif c == 'log':          log_setup()
    elif c == 'profile':      profile()
    elif c == 'tar':          do_logs(c)
    elif c == 'clean':        do_logs(c)
    elif c == 'all':
      setup_perf()
      profile(True)
      do_logs('tar')
    elif c == 'build':        build_kernel()
    else:
      C.error("Unknown command: '%s' !"%c)
      return -1
  return 0

if __name__ == "__main__":
  main()
  do['cmds_file'].close()

