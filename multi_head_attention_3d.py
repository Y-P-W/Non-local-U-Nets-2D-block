import torch
import torch.nn.functional as F
import torch.nn as nn


class multi_head_attention_3d(torch.nn.Module):
    def __init__(self, in_channel, key_filters, value_filters,
                 output_filters, num_heads, dropout_prob=0.5, layer_type='SAME'):
        super().__init__()
        """Multihead scaled-dot-product attention (3d) with input/output transformations.

        Args:
            inputs: a Tensor with shape [batch, d, h, w, channels]
            key_filters: an integer. Note that queries have the same number 
                of channels as keys
            value_filters: an integer
            output_depth: an integer
            num_heads: an integer dividing key_filters and value_filters
            layer_type: a string, type of this layer -- SAME, DOWN, UP
        Returns:
            A Tensor of shape [batch, _h, _w, output_filters]

        Raises:
            ValueError: if the key_filters or value_filters are not divisible
                by the number of attention heads.
        """

        if key_filters % num_heads != 0:
            raise ValueError("Key depth (%d) must be divisible by the number of "
                             "attention heads (%d)." % (key_filters, num_heads))
        if value_filters % num_heads != 0:
            raise ValueError("Value depth (%d) must be divisible by the number of "
                             "attention heads (%d)." % (value_filters, num_heads))
        if layer_type not in ['SAME', 'DOWN', 'UP']:
            raise ValueError("Layer type (%s) must be one of SAME, "
                             "DOWN, UP." % (layer_type))

        self.num_heads = num_heads
        self.layer_type = layer_type

        self.QueryTransform = None
        if layer_type == 'SAME':
            self.QueryTransform = nn.Conv3d(in_channel, key_filters, kernel_size=1, stride=1,
                                            padding=0, bias=True)
        elif layer_type == 'DOWN':
            self.QueryTransform = nn.Conv3d(in_channel, key_filters, kernel_size=3, stride=2,
                                            padding=1, bias=True)  # author use bias
        elif layer_type == 'UP':
            self.QueryTransform = nn.ConvTranspose3d(in_channel, key_filters, kernel_size=3, stride=2,
                                                     padding=1, bias=True)

        self.KeyTransform = nn.Conv3d(in_channel, key_filters, kernel_size=1, stride=1, padding=0, bias=True)
        self.ValueTransform = nn.Conv3d(in_channel, value_filters, kernel_size=1, stride=1, padding=0, bias=True)
        self.attention_dropout = nn.Dropout(dropout_prob)

        self.outputConv = nn.Conv3d(value_filters, output_filters, kernel_size=1, stride=1, padding=0, bias=True)

        self._scale = (key_filters // num_heads) ** 0.5

    def forward(self, inputs):
        """
        :param inputs: B, C, D, H, W
        :return: inputs: B, Co, Dq, Hq, Wq
        """

        if self.layer_type == 'SAME' or self.layer_type == 'DOWN':
            q = self.QueryTransform(inputs)
        elif self.layer_type == 'UP':
            q = self.QueryTransform(inputs, output_size=(inputs.shape[2] * 2, inputs.shape[3] * 2, inputs.shape[4] * 2))

        # [B, Dq, Hq, Wq, Ck]
        k = self.KeyTransform(inputs).permute(0, 2, 3, 4, 1)
        v = self.ValueTransform(inputs).permute(0, 2, 3, 4, 1)
        q = q.permute(0, 2, 3, 4, 1)

        Batch, Dq, Hq, Wq = q.shape[0], q.shape[1], q.shape[2], q.shape[3]

        # [B, D, H, W, N, Ck]
        k = self.split_heads(k, self.num_heads)
        v = self.split_heads(v, self.num_heads)
        q = self.split_heads(q, self.num_heads)

        # [(B, D, H, W, N), c]
        k = torch.flatten(k, 0, 4)
        v = torch.flatten(v, 0, 4)
        q = torch.flatten(q, 0, 4)

        # normalize
        q = q / self._scale
        # attention
        # [(B, Dq, Hq, Wq, N), (B, D, H, W, N)]
        A = torch.matmul(q, k.transpose(0, 1))
        A = torch.softmax(A, dim=1)
        A = self.attention_dropout(A)

        # [(B, Dq, Hq, Wq, N), C]
        O = torch.matmul(A, v)
        # [B, Dq, Hq, Wq, C]
        O = O.view(Batch, Dq,Hq, Wq, v.shape[-1] * self.num_heads)
        # [B, C, Dq, Hq, Wq]
        O = O.permute(0, 4, 1, 2, 3)
        # [B, Co, Dq, Hq, Wq]
        O = self.outputConv(O)

        return O

    def split_heads(self, x, num_heads):
        """Split channels (last dimension) into multiple heads.

        Args:
            x: a Tensor with shape [batch, h, w, channels]
            num_heads: an integer

        Returns:
            a Tensor with shape [batch, h, w, num_heads, channels / num_heads]
        """

        channel_num = x.shape[-1]
        return x.view(x.shape[0], x.shape[1], x.shape[2], x.shape[3], num_heads, int(channel_num / num_heads))


if __name__ == '__main__':
    device = torch.device('cpu')  # cuda:0
    inputs = torch.rand(1, 2, 6, 6).unsqueeze(0).to(device)
    net = multi_head_attention_3d(1, 2, 2, 3, 1, 0.5, 'UP')  # 'SAME', 'DOWN', 'UP'
    res = net(inputs)
    print('res shape:', res.shape)
