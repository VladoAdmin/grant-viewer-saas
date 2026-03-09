#!/usr/bin/env python3
"""Smart chunking for legal/grant documents.

Chunks by semantic structure (headings, sections) rather than token count.
Preserves legal document hierarchy.
"""

import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

@dataclass
class Chunk:
    text: str
    chunk_type: str  # 'heading', 'body', 'list', 'mixed'
    section_path: List[str]  # hierarchical path: ["1. VÝZVA", "1.1 Identifikácia"]
    level: int  # heading level (0 = root, 1 = main section, etc.)
    start_pos: int  # position in original text
    end_pos: int
    parent_heading: Optional[str] = None


class SmartChunker:
    """Chunker optimized for legal/grant documents."""
    
    # Patterns for Slovak legal documents
    HEADING_PATTERNS = [
        # Numbered sections: "1. NÁZEV", "1.1 Podsekce", "1.1.1 Detail"
        (r'^\s*(\d+)\.\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 1),
        (r'^\s*(\d+)\.(\d+)\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 2),
        (r'^\s*(\d+)\.(\d+)\.(\d+)\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 3),
        # Letter sections: "a) Název", "b) Podmínky"
        (r'^\s*([a-z])\)\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 2),
        # Roman numerals: "I. Název", "II. Podmínky"
        (r'^\s*([IVX]+)\.\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 1),
        # Section markers: "§ 5", "§ 12 Odst. 3"
        (r'^\s*(§\s*\d+[^.]*$)', 1),
    ]
    
    # Max chunk sizes (in characters, not tokens)
    MAX_CHUNK_SIZE = 3000  # ~600-800 tokens
    MIN_CHUNK_SIZE = 200   # ~40-50 tokens
    
    def __init__(self):
        self.section_stack: List[Tuple[str, int]] = []  # (heading, level)
    
    def _is_heading(self, line: str) -> Tuple[bool, int, str]:
        """Check if line is a heading and return (is_heading, level, clean_text)."""
        line = line.strip()
        if not line:
            return False, 0, ""
        
        for pattern, level in self.HEADING_PATTERNS:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                return True, level, line
        
        return False, 0, line
    
    def _update_section_stack(self, heading: str, level: int):
        """Update hierarchical section stack."""
        # Pop sections that are deeper or same level
        while self.section_stack and self.section_stack[-1][1] >= level:
            self.section_stack.pop()
        self.section_stack.append((heading, level))
    
    def _get_section_path(self) -> List[str]:
        """Get current hierarchical path."""
        return [h for h, _ in self.section_stack]
    
    def _get_parent_heading(self) -> Optional[str]:
        """Get immediate parent heading."""
        if len(self.section_stack) >= 2:
            return self.section_stack[-2][0]
        return None
    
    def chunk(self, text: str) -> List[Chunk]:
        """
        Main chunking method.
        
        Strategy:
        1. Split by headings
        2. Within each section, chunk by paragraphs
        3. Respect MAX_CHUNK_SIZE - don't break mid-sentence
        4. Preserve lists and tables as atomic units when possible
        """
        lines = text.split('\n')
        chunks: List[Chunk] = []
        
        current_buffer: List[str] = []
        current_start = 0
        current_type = "body"
        
        i = 0
        while i < len(lines):
            line = lines[i]
            is_heading, level, clean_line = self._is_heading(line)
            
            if is_heading:
                # Flush current buffer as a chunk
                if current_buffer:
                    chunk_text = '\n'.join(current_buffer).strip()
                    if len(chunk_text) >= self.MIN_CHUNK_SIZE:
                        chunks.append(Chunk(
                            text=chunk_text,
                            chunk_type=current_type,
                            section_path=self._get_section_path(),
                            level=self.section_stack[-1][1] if self.section_stack else 0,
                            start_pos=current_start,
                            end_pos=i,
                            parent_heading=self._get_parent_heading()
                        ))
                    current_buffer = []
                
                # Update section hierarchy
                self._update_section_stack(clean_line, level)
                
                # Create heading chunk
                chunks.append(Chunk(
                    text=clean_line,
                    chunk_type="heading",
                    section_path=self._get_section_path(),
                    level=level,
                    start_pos=i,
                    end_pos=i+1,
                    parent_heading=self._get_parent_heading()
                ))
                
                current_start = i + 1
                i += 1
                continue
            
            # Detect content type
            stripped = line.strip()
            if stripped.startswith(('•', '-', '*', '○', '▪')) or re.match(r'^\d+\.', stripped):
                current_type = "list"
            
            # Add to buffer
            current_buffer.append(line)
            
            # Check if we should flush (size limit)
            current_text = '\n'.join(current_buffer)
            if len(current_text) >= self.MAX_CHUNK_SIZE:
                # Try to break at paragraph boundary
                flush_idx = len(current_buffer)
                for j in range(len(current_buffer) - 1, max(0, len(current_buffer) - 5), -1):
                    if current_buffer[j].strip() == '' or current_buffer[j].strip().endswith('.'):
                        flush_idx = j + 1
                        break
                
                chunk_text = '\n'.join(current_buffer[:flush_idx]).strip()
                if len(chunk_text) >= self.MIN_CHUNK_SIZE:
                    chunks.append(Chunk(
                        text=chunk_text,
                        chunk_type=current_type,
                        section_path=self._get_section_path(),
                        level=self.section_stack[-1][1] if self.section_stack else 0,
                        start_pos=current_start,
                        end_pos=i - (len(current_buffer) - flush_idx),
                        parent_heading=self._get_parent_heading()
                    ))
                
                current_buffer = current_buffer[flush_idx:]
                current_start = i - len(current_buffer) + 1
                current_type = "body"  # Reset type
            
            i += 1
        
        # Flush remaining buffer
        if current_buffer:
            chunk_text = '\n'.join(current_buffer).strip()
            if len(chunk_text) >= self.MIN_CHUNK_SIZE:
                chunks.append(Chunk(
                    text=chunk_text,
                    chunk_type=current_type,
                    section_path=self._get_section_path(),
                    level=self.section_stack[-1][1] if self.section_stack else 0,
                    start_pos=current_start,
                    end_pos=len(lines),
                    parent_heading=self._get_parent_heading()
                ))
        
        return chunks
    
    def chunk_with_context(self, text: str) -> List[Dict]:
        """Chunk and return enriched chunks with context.
        
        Post-processing:
        - For heading-only chunks, append next body chunk(s) for richer embedding
        - Keep chunk boundaries for navigation, but enrich for search
        """
        chunks = self.chunk(text)
        result = []
        
        for i, chunk in enumerate(chunks):
            # Build enriched text for embedding (include following body if this is heading)
            text_for_embedding = chunk.text
            
            if chunk.chunk_type == "heading" and i + 1 < len(chunks):
                next_chunk = chunks[i + 1]
                # If next is body in same section, append it for embedding context
                if (next_chunk.chunk_type != "heading" and 
                    len(next_chunk.section_path) > 0 and
                    next_chunk.section_path[-1] == chunk.section_path[-1]):
                    text_for_embedding = f"{chunk.text}\n\n{next_chunk.text[:1000]}"
            
            # Build context window
            prev_text = chunks[i-1].text[:200] if i > 0 and chunks[i-1].chunk_type != "heading" else ""
            next_text = chunks[i+1].text[:200] if i < len(chunks) - 1 and chunks[i+1].chunk_type != "heading" else ""
            
            # Add section context to text
            section_context = " > ".join(chunk.section_path[-2:]) if len(chunk.section_path) >= 2 else ""
            
            display_text = chunk.text
            if section_context and chunk.chunk_type != "heading":
                display_text = f"[{section_context}]\n{chunk.text}"
            
            result.append({
                "text": text_for_embedding,  # Used for embedding (richer for headings)
                "raw_text": chunk.text,      # Original chunk text (for display)
                "display_text": display_text,  # Display version (with section context)
                "type": chunk.chunk_type,
                "section_path": chunk.section_path,
                "level": chunk.level,
                "context_before": prev_text,
                "context_after": next_text,
                "has_heading_parent": chunk.parent_heading is not None,
            })
        
        return result


def compare_chunkers(text: str):
    """Compare old vs new chunking strategy."""
    import tiktoken
    enc = tiktoken.encoding_for_model("gpt-4")
    
    # Old: token-based
    def old_chunk(text, target=800):
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks, current, current_len = [], [], 0
        for para in paragraphs:
            para_len = len(enc.encode(para))
            if current_len + para_len > target and current:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            current.append(para)
            current_len += para_len
        if current:
            chunks.append("\n".join(current))
        return chunks
    
    # New: semantic
    smart = SmartChunker()
    new_chunks = smart.chunk_with_context(text)
    
    old_chunks = old_chunk(text)
    
    print(f"OLD (token-based): {len(old_chunks)} chunks")
    for i, c in enumerate(old_chunks[:3]):
        print(f"  Chunk {i+1}: {len(enc.encode(c))} tokens, {len(c)} chars")
        print(f"    Preview: {c[:100]}...")
    
    print(f"\nNEW (semantic): {len(new_chunks)} chunks")
    for i, c in enumerate(new_chunks[:5]):
        print(f"  Chunk {i+1}: {len(enc.encode(c['text']))} tokens, type={c['type']}")
        print(f"    Path: {' > '.join(c['section_path'][-2:]) if c['section_path'] else 'root'}")
        print(f"    Preview: {c['raw_text'][:100]}...")
    
    return old_chunks, new_chunks


if __name__ == "__main__":
    # Test with sample text
    sample = """
1. VŠEOBECNÉ INFORMÁCIE
Fond poskytuje podporu formou Dotácie v zmysle Zákona o Fonde.
Táto Príručka pre Žiadateľa je určená pre Žiadateľov.

2. PODMIENKY ŽIADANIA
2.1 Oprávnení žiadatelia
Žiadateľom môže byť právnická osoba alebo fyzická osoba.
Podmienkou je registrácia v Slovenskej republike.

2.2 Nevyhnutné náklady
Medzi oprávnené náklady patria:
• náklady na prípravu projektu
• náklady na realizáciu
• náklady na administráciu

3. PROCES HODNOTENIA
Žiadosti sa hodnotia podľa týchto kritérií:
a) Relevancia projektu
b) Kvalita predloženého riešenia
c) Udržateľnosť projektu
"""
    
    compare_chunkers(sample)
