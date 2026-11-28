% base workspace'teki Simulink.Parameter ve Simulink.LookupTable nesnelerini JSON olarak listeler.
% GUI (MATLAB Engine) cagirir: text = mil_list_params(). Gercek MATLAB'da DOGRULANMADI.
function json = mil_list_params()
    w = evalin('base', 'whos');
    items = {};
    for i = 1:numel(w)
        cls = w(i).class;
        if ~any(strcmp(cls, {'Simulink.Parameter', 'Simulink.LookupTable'}))
            continue;
        end
        n = w(i).name;
        it = struct('name', n, 'class', cls);
        try
            o = evalin('base', n);
            if strcmp(cls, 'Simulink.Parameter')
                v = o.Value;
                it.kind = 'param';
                it.mclass = class(v);
                it.dims = size(v);
                it.unit = o.Unit;
                it.min = o.Min;
                it.max = o.Max;
                it.storage = o.CoderInfo.StorageClass;
                it.breakpoints = {};
            else
                t = o.Table;
                v = t.Value;
                it.kind = 'lut';
                it.mclass = class(v);
                it.dims = size(v);
                it.unit = t.Unit;
                it.min = t.Min;
                it.max = t.Max;
                it.storage = o.CoderInfo.StorageClass;
                it.bpspec = o.BreakpointsSpecification;
                bps = cell(1, numel(o.Breakpoints));
                for k = 1:numel(o.Breakpoints)
                    b = o.Breakpoints{k};
                    bps{k} = struct('values', b.Value(:)', 'unit', b.Unit);
                end
                it.breakpoints = bps;
            end
        catch ex
            it.error = ex.message;
        end
        items{end + 1} = it; %#ok<AGROW>
    end
    json = jsonencode(items);
end
