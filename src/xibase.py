'''
Xi Base for LSTM
'''
import math
import torch
import torch.nn.functional as F
import numpy as np

from torch.autograd import (
    Variable,
)
from torch.nn import (
    Module,
    Parameter,
)
from torch.nn.modules.rnn import (
    RNNCellBase,
)


def clip_grad(v, min, max):
    '''
    unknown strange function from Xi
    '''
    v.register_hook(lambda g: g.clamp(min, max))
    return v


class XiRNNBase(Module):
    '''
    for xi
    '''
    def __init__(
            self,
            mode,
            input_size,
            hidden_size,
            recurrent_size=None,
            num_layers=1,
            bias=True,
            return_sequences=True,
            grad_clip=None,
            bidirectional=False,
    ):
        super(XiRNNBase, self).__init__()
        self.mode = mode
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.recurrent_size = recurrent_size
        self.num_layers = num_layers
        self.bias = bias
        self.return_sequences = return_sequences
        self.grad_clip = grad_clip
        self.bidirectional = bidirectional

        self.num_directions = 2 if bidirectional else 1

        mode2cell = {
            'LSTMP': LSTMPCell,
            'LSTMO': LSTMOCell,
        }
        Cell = mode2cell[mode]

        kwargs = {'input_size': input_size,
                  'hidden_size': hidden_size,
                  'bias': bias,
                  'grad_clip': grad_clip}
        if self.mode == 'LSTMP' or self.mode == 'LSTMO':
            kwargs['recurrent_size'] = recurrent_size

        self.cell0 = Cell(**kwargs).cuda()
        if self.bidirectional:
            self.cell1 = Cell(**kwargs).cuda()
        for i in range(1, num_layers):
            kwargs['input_size'] = recurrent_size if self.mode == 'LSTMP' else hidden_size
            cell = Cell(**kwargs).cuda()
            setattr(self, 'cell{}'.format(i), cell)

    def forward(self, input, initial_states, lengths):
        if initial_states is None:
            zeros = Variable(torch.zeros(input.size(0), self.hidden_size).cuda())
            if self.mode == 'LSTMP':
                zeros_h = Variable(torch.zeros(input.size(0), self.recurrent_size).cuda())
                initial_states = [(zeros_h, zeros), ] * self.num_layers
            elif self.mode == 'LSTMO':
                zeros_h = Variable(torch.zeros(input.size(0), self.recurrent_size).cuda())
                initial_states = [(zeros_h, zeros, zeros_h), ] * self.num_layers
            else:
                initial_states = [zeros] * self.num_layers

            initial_states = [initial_states] * self.num_directions
        assert len(initial_states) == self.num_directions

        states = initial_states[0]
        outputs = []
        length_matrix = np.zeros((64, 188))
        for i in range(len(lengths)):
            for j in range(lengths[i]):
                length_matrix[i][j] = 1

        time_steps = 188
        for t in range(time_steps):
            x = input[:, t, :]
            # for l in range(self.num_layers):
            if self.mode == 'LSTMP':
                hx, cx = getattr(self, 'cell{}'.format(0))(x, states[0])
            elif self.mode == 'LSTMO':
                hx, cx, tx = getattr(self, 'cell{}'.format(0))(x, states[0])
            for j in range(len(length_matrix)):
                if length_matrix[j][t]==0:
                    if self.mode == 'LSTMP':
                        index = Variable(torch.LongTensor([j]))
                        hx = hx.clone()
                        cx = cx.clone()
                        hx.index_fill_(0,index,0)
                        cx.index_fill_(0,index,0)

                    elif self.mode == 'LSTMO':
                        index = Variable(torch.LongTensor([j]))
                        hx = hx.clone()
                        cx = cx.clone()
                        tx = tx.clone()
                        hx.index_fill_(0,index,0)
                        cx.index_fill_(0,index,0)
                        tx.index_fill_(0,index,0)
            if self.mode == 'LSTMP':
                states[0] = (hx,cx)
                output_item = (hx,cx)
                outputs.append(output_item)
            elif self.mode == 'LSTMO':
                states[0] = (hx,cx,tx)
                output_item = (hx,cx,tx)
                outputs.append(output_item)

        outputs_bidirectional = []
        if self.bidirectional:
            states = initial_states[1]
            for t in range(time_steps):
                x = input[:, time_steps-t-1, :]
                # for l in range(self.num_layers):
                if self.mode == 'LSTMP':
                    hx,cx = getattr(self, 'cell{}'.format(1))(x, states[0])
                elif self.mode == 'LSTMO':
                    hx,cx,tx = getattr(self, 'cell{}'.format(1))(x, states[0])
                for j in range(len(length_matrix)):
                    index = Variable(torch.LongTensor([j]))
                    if self.mode == 'LSTMP':
                        hx = hx.clone()
                        cx = cx.clone()
                        hx.index_fill_(0,index,0)
                        cx.index_fill_(0,index,0)
                    elif self.mode == 'LSTMO':
                        hx = hx.clone()
                        cx = cx.clone()
                        tx = tx.clone()
                        hx.index_fill_(0,index,0)
                        cx.index_fill_(0,index,0)
                        tx.index_fill_(0,index,0)
                if self.mode == 'LSTMP':
                    states[0] = (hx,cx)
                    output_item = (hx,cx)
                    outputs_bidirectional.append(output_item)
                elif self.mode == 'LSTMO':
                    states[0] = (hx,cx,tx)
                    output_item = (hx,cx,tx)
                    outputs_bidirectional.append(output_item)
            outputs_bidirectional.reverse()

        if self.bidirectional:
            if self.return_sequences:
                if self.mode.startswith('LSTMO'):
                    hs, cs, ts = zip(*outputs)
                    hs_b, cs_b, ts_b = zip(*outputs_bidirectional)

                    h = torch.stack(hs).transpose(0, 1)
                    c = torch.stack(cs).transpose(0, 1)
                    t = torch.stack(ts).transpose(0, 1)

                    h_b = torch.stack(hs_b).transpose(0, 1)
                    c_b = torch.stack(cs_b).transpose(0, 1)
                    t_b = torch.stack(ts_b).transpose(0, 1)

                    h_o = torch.cat((h, h_b), -1)
                    c_o = torch.cat((c, c_b), -1)
                    t_o = torch.cat((t, t_b), -1)

                    output = (h_o, c_o, t_o)
                elif self.mode.startswith('LSTM'):
                    hs, cs = zip(*outputs)
                    hs_b, cs_b = zip(*outputs_bidirectional)
                    h = torch.stack(hs).transpose(0, 1)
                    c = torch.stack(cs).transpose(0, 1)
                    h_b = torch.stack(hs_b).transpose(0, 1)
                    c_b = torch.stack(cs_b).transpose(0, 1)

                    h_o = torch.cat((h, h_b), -1)
                    c_o = torch.cat((c, c_b), -1)

                    output = (h_o, c_o)
                else:
                    output = torch.stack(outputs).transpose(0, 1)
            else:
                output = outputs[-1]
        else:
            if self.return_sequences:
                if self.mode.startswith('LSTMO'):
                    hs, cs, ts = zip(*outputs)
                    h = torch.stack(hs).transpose(0, 1)
                    c = torch.stack(cs).transpose(0, 1)
                    t = torch.stack(ts).transpose(0, 1)
                    output = (h, c, t)
                elif self.mode.startswith('LSTM'):
                    hs, cs = zip(*outputs)
                    h = torch.stack(hs).transpose(0, 1)
                    c = torch.stack(cs).transpose(0, 1)
                    output = (h, c)
                else:
                    output = torch.stack(outputs).transpose(0, 1)
            else:
                output = outputs[-1]

        return output


class LSTMOCell(RNNCellBase):
    '''
    LSTM Output
    '''
    def __init__(
            self,
            input_size,
            hidden_size,
            recurrent_size,
            bias=True,
            grad_clip=None,
    ):
        super(LSTMOCell, self).__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.recurrent_size = recurrent_size
        self.grad_clip = grad_clip

        self.weight_ih = Parameter(torch.Tensor(4 * hidden_size, input_size))
        self.weight_hh = Parameter(torch.Tensor(4 * hidden_size, recurrent_size))
        self.weight_rec = Parameter(torch.Tensor(recurrent_size, hidden_size))
        self.weight_t = Parameter(torch.Tensor(hidden_size, hidden_size))
        self.weight_ret = Parameter(torch.Tensor(3 * hidden_size, hidden_size))

        if bias:
            self.bias = Parameter(torch.Tensor(4 * hidden_size))
            self.bias_t = Parameter(torch.Tensor(hidden_size))
        else:
            self.register_parameter('bias', None)

        self.reset_parameters()

    def reset_parameters(self):
        '''
        reset
        '''
        stdv = 1.0 / math.sqrt(self.hidden_size)
        for weight in self.parameters():
            weight.data.uniform_(-stdv, stdv)

    def forward(self, input, hx):
        '''
        forward
        '''
        h, c, t = hx

        pre = F.linear(input, self.weight_ih, self.bias) + F.linear(h, self.weight_hh)
        pre_t = F.linear(t, self.weight_ret)

        if self.grad_clip:
            pre = clip_grad(pre, -self.grad_clip, self.grad_clip)

        i = F.sigmoid(pre_t[:, :self.hidden_size] + pre_t[:, : self.hidden_size])
        f = F.sigmoid(pre_t[:, self.hidden_size: self.hidden_size * 2] + pre_t[:, self.hidden_size: self.hidden_size * 2])
        g = F.tanh(pre_t[:, self.hidden_size * 2: self.hidden_size * 3] + pre_t[:, self.hidden_size * 2 : self.hidden_size * 3])
        c = f * c + i * g

        o = F.sigmoid(pre[:, self.hidden_size * 3:] + F.linear(c, self.weight_rec))

        h = o * F.tanh(c)
        t = F.linear(h, self.weight_t, self.bias_t)
        return h, c, t


class LSTMO(XiRNNBase):
    '''
    LSTM Output
    '''
    def __init__(self, *args, **kwargs):
        super(LSTMO, self).__init__('LSTMO', *args, **kwargs)


class LSTMPCell(RNNCellBase):
    '''
    peephole
    '''

    def __init__(
            self,
            input_size,
            hidden_size,
            recurrent_size,
            bias=True,
            grad_clip=None,
    ):
        super(LSTMPCell, self).__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.recurrent_size = recurrent_size
        self.grad_clip = grad_clip

        self.weight_ih = Parameter(torch.Tensor(4 * hidden_size, input_size))
        self.weight_hh = Parameter(torch.Tensor(4 * hidden_size, recurrent_size))
        self.weight_rec = Parameter(torch.Tensor(2 * recurrent_size, hidden_size))
        if bias:
            self.bias = Parameter(torch.Tensor(4 * hidden_size))
        else:
            self.register_parameter('bias', None)

        self.reset_parameters()

    def reset_parameters(self):
        '''
        reset
        '''
        stdv = 1.0 / math.sqrt(self.hidden_size)
        for weight in self.parameters():
            weight.data.uniform_(-stdv, stdv)

    def forward(self, input, hx):
        h, c = hx

        pre = F.linear(input, self.weight_ih, self.bias)
        pre += F.linear(h, self.weight_hh)

        pre_c = F.linear(c, self.weight_rec)
        if self.grad_clip:
            pre = clip_grad(pre, -self.grad_clip, self.grad_clip)

        i = F.sigmoid(pre[:, :self.hidden_size] + pre_c[:, :self.hidden_size])
        f = F.sigmoid(pre[:, self.hidden_size: self.hidden_size * 2] + pre_c[:, self.hidden_size : self.hidden_size * 2])
        g = F.tanh(pre[:, self.hidden_size * 2: self.hidden_size * 3])

        c = f * c + i * g
        o = F.sigmoid(pre[:, self.hidden_size * 3:] + c)
        h = o * F.tanh(c)
        return h, c


class LSTMP(XiRNNBase):
    '''
    LSTM peephole
    '''

    def __init__(self, *args, **kwargs):
        super(LSTMP, self).__init__('LSTMP', *args, **kwargs)
