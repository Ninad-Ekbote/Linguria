import torch
import torch.nn as nn
import math

class Inputembeddings(nn.Module):
    """Some Information about MyModule"""
    
    def __init__(self, d_model : int, vocab_size: int):
        super().__init__()
        self.d_model = d_model
        self.embeddings = nn.Embedding(vocab_size, d_model)

    def forward(self, x):

        return self.embeddings(x)*math.sqrt(self.d_model)
    

class positional_encoding(nn.Module):
    def __init__(self, d_model: int, seq_len: int, dropout: float) -> None:
        super().__init__()
        self.d_model = d_model
        self.seq_len = seq_len
        self.dropout = nn.Dropout(dropout)
        # Create a matrix of shape (seq_len, d_model)
        pe = torch.zeros(seq_len, d_model)
        # Create a vector of shape (seq_len)
        position = torch.arange(0, seq_len, dtype=torch.float).unsqueeze(1) # (seq_len, 1)
        # Create a vector of shape (d_model)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)) # (d_model / 2)
        # Apply sine to even indices
        pe[:, 0::2] = torch.sin(position * div_term) # sin(position * (10000 ** (2i / d_model))
        # Apply cosine to odd indices
        pe[:, 1::2] = torch.cos(position * div_term) # cos(position * (10000 ** (2i / d_model))
        # Add a batch dimension to the positional encoding
        pe = pe.unsqueeze(0) # (1, seq_len, d_model)
        # Register the positional encoding as a buffer
        self.register_buffer('pe', pe)

    def forward(self, x):
        # print()
        # print(x[0][0][0],x[0][0][0].type)
        # print()
        # print(self.pe)
        
        x = x + (self.pe[:, :x.shape[1], :]).requires_grad_(False) # (batch, seq_len, d_model)
        return self.dropout(x)

        
    

class layernormalization(nn.Module):
    def __init__(self,features:int, eps: float= 10**-6):
        super().__init__()
        self.eps=eps
        self.alpha = nn.Parameter(torch.ones(features))
        self.bias = nn.Parameter(torch.zeros(features))

    def forward(self,x):
        mean = x.mean(dim=-1, keepdim=True)
        std = x.std(dim=-1,keepdim=True)

        return self.alpha * (x-mean)/(std + self.eps) + self.bias
    
class ff(nn.Module):
    def __init__(self,d_model : int , d_ff :int ,dropout: float):
        super().__init__()
        self.linear_1 = nn.Linear(d_model,d_ff)
        self.drop = nn.Dropout(dropout)
        self.linear_2 = nn.Linear(d_ff, d_model)
    
    def forward(self, x):
        return self.linear_2(self.drop(torch.relu(self.linear_1(x))))
    
class MultiAttention(nn.Module):
    def __init__(self, d_model : int , h :int ,dropout: float) -> None:
        super().__init__()

        self.d_model = d_model
        self.h = h

        assert d_model %h == 0, "d_model is not divisible from by h"

        self.d_k = d_model//h
        self.w_q = nn.Linear(d_model, d_model)
        self.w_k = nn.Linear(d_model, d_model)
        self.w_v = nn.Linear(d_model, d_model)


        self.w_o = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)

    @staticmethod
    def attention(query, key, value, mask, dropout: nn.Dropout):
        d_k = query.shape[-1]

        attention_scores = (query @ key.transpose(-2,-1))/ math.sqrt(d_k)
        if mask is not None:
            attention_scores.masked_fill_(mask==0,-1e9)
        attention_scores = attention_scores.softmax(dim=-1)

        if dropout is not None:
            attention_scores = dropout(attention_scores)

        return (attention_scores @ value), attention_scores


    def forward(self, q, k , v, mask):
        query = self.w_q(q)
        key = self.w_k(k)
        value = self.w_v(v)

        query = query.view(query.shape[0],query.shape[1], self.h, self.d_k).transpose(1,2)
        key = key.view(key.shape[0],key.shape[1], self.h, self.d_k).transpose(1,2)
        value = value.view(value.shape[0],value.shape[1], self.h, self.d_k).transpose(1,2)

        x, self.attention_scores = MultiAttention.attention(query, key, value, mask, self.dropout)

        
        x = x.transpose(1,2).contiguous().view(x.shape[0],-1,self.h*self.d_k)

        return self.w_o(x)
    

class ResidualConnection(nn.Module):

    def __init__(self, features:int , dropout : float) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.norm = layernormalization(features)


    def forward(self,x, sublayer):

        return x + self.dropout(sublayer(self.norm(x)))
    

class EncoderBlock(nn.Module):

    def __init__(self, features, self_attention_block: MultiAttention, feed_forward_block: ff, dropout: float)->None:
        
        super().__init__()

        self.self_attention_block = self_attention_block
        self.feed_forward_block = feed_forward_block
        self.residual_connections = nn.ModuleList([ResidualConnection(features, dropout) for _ in range(2)])



    def forward(self, x, src_mask):
        x = self.residual_connections[0](x, lambda x: self.self_attention_block(x,x,x, src_mask))
        x = self.residual_connections[1](x, self.feed_forward_block)

        return x

class Encoder(nn.Module):

    def __init__(self,features:int,  layers:nn.ModuleList) -> None:
        super().__init__()
        self.layers = layers
        self.norm = layernormalization(features)

    def forward(self, x, mask):
        for layer in self.layers:
            x=layer(x, mask)

        return self.norm(x)
    

class DecoderBlock(nn.Module):

    def __init__(self, features:int,  self_attention_block: MultiAttention, cross_attention_block: MultiAttention,  feed_forward_block: ff, dropout: float)->None:
        super().__init__()

        self.self_attention_block = self_attention_block
        self.feed_forward_block = feed_forward_block
        self.cross_attention_block = cross_attention_block
        self.residual_connection = nn.ModuleList([ResidualConnection(features,dropout) for _ in range(3)])

    def forward(self, x, encoder_output, src_mask, tgt_mask):
        x = self.residual_connection[0](x, lambda x: self.self_attention_block(x,x,x, tgt_mask))
        x = self.residual_connection[1](x, lambda x: self.cross_attention_block(x,encoder_output,encoder_output, src_mask))
        x = self.residual_connection[2](x, self.feed_forward_block)
        return x
    

class Decoder(nn.Module):
    def __init__(self,features:int, layers:nn.ModuleList) -> None:
        super().__init__()
        self.layers = layers
        self.norm = layernormalization(features)

    def forward(self, x, encoder_output,  src_mask, tgt_mask):
        for layer in self.layers:
            x=layer(x, encoder_output,  src_mask, tgt_mask)

        return self.norm(x)

class ProjectLayer(nn.Module):

    def __init__(self, d_model: int, vocab_size: int) -> None:
        super().__init__()
        self.proj = nn.Linear(d_model, vocab_size)

    def forward(self,x):
        return self.proj(x)

class Transformer(nn.Module):
    def __init__(self, encoder: Encoder, decoder: Decoder, src_embed : Inputembeddings, tgt_embed: Inputembeddings, src_pos: positional_encoding, tgt_pos : positional_encoding, projection : ProjectLayer):
        super().__init__()

        self.encoder = encoder
        self.decoder = decoder
        self.src_embed = src_embed
        self.tgt_embed = tgt_embed
        self.src_pos = src_pos
        self.tgt_pos =tgt_pos
        self.projection = projection

    def encode(self, src, src_mask):
        src  = self.src_embed(src)
        src =  self.src_pos(src)
        return self.encoder(src, src_mask)

    def decode(self, encoder_output, src_mask, tgt, tgt_mask):
        tgt  = self.tgt_embed(tgt)
        tgt =  self.tgt_pos(tgt)
        return self.decoder(tgt, encoder_output, src_mask, tgt_mask)
    
    def project(self, x):
        return self.projection(x)
    

def build_transformer(src_vocab_size: int, tgt_vocab_size: int, src_seg_len: int, tgt_seg_len:int, d_model: int=512, N: int=6, h: int = 8, dropout: float=0.1, d_ff = 2048)-> Transformer:

    src_embed = Inputembeddings(d_model, src_vocab_size)
    tgt_embed = Inputembeddings(d_model, tgt_vocab_size)

    src_pos = positional_encoding(d_model,src_seg_len, dropout)
    tgt_pos = positional_encoding(d_model,tgt_seg_len, dropout)

    encoder_block = []

    for _ in range(N):
        encoder_self_attention_block = MultiAttention(d_model, h, dropout)
        feedforward = ff(d_model, d_ff, dropout)
        encoderblock = EncoderBlock(d_model,encoder_self_attention_block, feedforward, dropout)
        encoder_block.append(encoderblock)

    decoder_block = []

    for _ in range(N):
        decoder_self_attention_block = MultiAttention(d_model, h, dropout)
        decoder_cross_attention_block = MultiAttention(d_model, h, dropout)
        feedforward = ff(d_model, d_ff, dropout)
        decoderblock = DecoderBlock(d_model, decoder_self_attention_block, decoder_cross_attention_block, feedforward, dropout)
        decoder_block.append(decoderblock)

    encoder = Encoder(d_model,nn.ModuleList(encoder_block))
    decoder = Decoder(d_model,nn.ModuleList(decoder_block))

    projection_layer = ProjectLayer(d_model, tgt_vocab_size)

    transformer = Transformer(encoder, decoder, src_embed , tgt_embed, src_pos, tgt_pos, projection_layer)

    for p in transformer.parameters():
        if p.dim()>1:
            nn.init.xavier_uniform(p)

    return transformer














    


