import { Column, CreateDateColumn, Entity, PrimaryGeneratedColumn, UpdateDateColumn } from "typeorm";
import { DocumentRepository, ProcessingStatus } from "./document-status.enum";

@Entity("documents")
export class DocumentEntity {
  @PrimaryGeneratedColumn("uuid")
  id!: string;

  @Column({ name: "original_filename" })
  originalFilename!: string;

  @Column({ name: "s3_path" })
  s3Path!: string;

  @Column({ name: "current_repository", type: "enum", enum: DocumentRepository })
  currentRepository!: DocumentRepository;

  @Column({ name: "processing_status", type: "enum", enum: ProcessingStatus })
  processingStatus!: ProcessingStatus;

  @Column({ name: "uploaded_by" })
  uploadedBy!: string;

  @Column({ nullable: true })
  make?: string;

  @Column({ nullable: true })
  model?: string;

  @Column({ nullable: true })
  year?: number;

  @Column({ name: "warranty_type", nullable: true })
  warrantyType?: string;

  @Column({ nullable: true })
  country?: string;

  @Column({ name: "metadata_json", type: "jsonb", nullable: true })
  metadataJson?: Record<string, unknown>;

  @Column({ name: "confidence_score", type: "float", nullable: true })
  confidenceScore?: number;

  @Column({ name: "error_message", type: "text", nullable: true })
  errorMessage?: string;

  @CreateDateColumn({ name: "uploaded_at" })
  uploadedAt!: Date;

  @UpdateDateColumn({ name: "updated_at" })
  updatedAt!: Date;
}
